from __future__ import annotations

import copy
import functools
import json
import hashlib
import math
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BusinessOraclePlanEvidence,
    business_family_for_api,
    write_business_oracle_plan,
)
from tests.semantic.support.codex_audio_conversion_runtime_v3 import (
    AudioConversionPlan,
    AudioConversionSnapshot,
    ConversionBinding,
    ConversionPreset,
    ConvertedArtifact,
    FileState,
    VolatileFileState,
    audio_conversion_volatile_cache_paths,
    derive_conversion_profiles,
)
from tests.semantic.support.codex_audio_media_business_plan_v3 import (
    compile_audio_conversion_business_plan,
)
from tests.semantic.support.codex_cli_business_plan_v3 import (
    compile_cli_business_plan,
)
from tests.semantic.support.codex_campaign import (
    CampaignEvidenceError,
    list_campaign_attempts,
    sha256_file,
    stable_tree_sha256,
)
from tests.semantic.support.codex_campaign_runner import (
    ChildValidation,
    PhaseVerdict,
    replace_expected_skill_symlinks,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_audio_import_composer_protocol,
    build_direct_protocol,
    build_object_set_composer_transaction_steps,
    build_transaction_protocol,
    query_object_step,
    query_schema_step,
    _typed_fact_cli_arguments,
)
from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    DraftTypedActionArgument,
    ExpectedGatewayStep,
    InlineTypedOperationArgument,
    MetadataQueryArgument,
    ResponseBinding,
    SemanticJsonArgument,
    TypedRequestFactsArgument,
    resolve_gateway_invocation,
)
from tests.semantic.support.codex_gateway_contracts import (
    GATEWAY_RESULT_CONTRACT,
    TYPED_CONTAINER_HANDLE_CONTRACT,
    gateway_payload_contracts,
)
from tests.semantic.support.codex_harness import (
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    audit_session_events,
    build_task_exec_command,
    build_task_resume_command,
    classify_task_commands,
    completed_command_records,
    count_invalid_jsonl_lines,
    discover_windows_powershell_core,
    final_agent_message,
    parse_jsonl_events,
    prepare_workspace_skill_install,
    turn_usage,
    workspace_skill_install_path,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceEvidence,
    prompt_materialization_receipt,
    read_prompt_provenance,
    write_prompt_provenance,
)
from tests.semantic.support.codex_object_business_plan_v3 import (
    compile_object_business_plan,
    validate_object_archived_verification,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    MaterializedObject,
    MaterializedReference,
    ObjectProperty,
    OperationRequestSpec,
    QueryObjectRequestSpec,
    build_object_heavy_v3_recipe,
)
from wwise_waapi.platform_commands import (
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    decode_windows_powershell_argv,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)
from wwise_waapi.operation_composer import (
    composition_projection,
    operation_composer_digest,
    typed_action_cli_arguments,
)
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.operation_registry import operation_request_schema_digest
from wwise_waapi.transaction_cleanup import transaction_cleanup_payload
from wwise_waapi.typed_operations import inline_operation_cli_arguments
from wwise_waapi.typed_requests import typed_request_construction_for_values
from tests.semantic.support.codex_object_runtime_v3 import ObjectRuntimeSnapshot
from tests.semantic.support.codex_soundbank_business_plan_v3 import (
    compile_soundbank_business_plan,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    PROCESS_REFUSAL_ERROR_CODE,
    SOUNDBANK_TOPIC,
)
from tests.semantic.test_codex_cli_runtime_v3 import (
    _build as _build_cli_runtime,
    _make_console as _make_cli_console,
    _seal as _seal_cli_runtime,
    _suite_cli_cases,
)
from tests.semantic.test_codex_soundbank_business_plan_v3 import (
    _case as _build_soundbank_case,
)
from wwise_waapi.transactions import (
    TransactionState,
    TransactionStore,
    confirmation_token_for,
)


def test_consumed_composer_order_rebinds_each_revision_to_its_actual_predecessor(
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "id",
                        "value": f"{{{index:08d}-1111-1111-1111-111111111111}}",
                    },
                    "properties": [{"name": "Volume", "value": index}],
                }
                for index in range(1, 4)
            ]
        },
    }
    canonical = build_object_set_composer_transaction_steps(
        request,
        label="tx01",
    )
    action_steps = [
        step for step in canonical if step.subcommand == "draft-apply"
    ]
    reordered_actions = [
        *(
            step
            for step in action_steps
            if step.arguments[-1].expected["action"] == "add_target"
        ),
        *(
            step
            for step in action_steps
            if step.arguments[-1].expected["action"] != "add_target"
        ),
    ]
    consumed = [step.name for step in canonical]
    action_indexes = [
        index
        for index, step in enumerate(canonical)
        if step.subcommand == "draft-apply"
    ]
    for index, step in zip(action_indexes, reordered_actions, strict=True):
        consumed[index] = step.name

    linearized = campaign._steps_in_consumed_order(canonical, consumed)

    latest = next(
        step.name for step in linearized if step.subcommand == "draft-start"
    )
    for step in linearized:
        if step.subcommand in {
            "draft-apply",
            "draft-check",
            "draft-cancel",
            "preview-from-draft",
        }:
            assert step.arguments[4] == ResponseBinding(
                latest,
                "/draft/revision",
            )
            latest = step.name
    CodexGatewayBroker(
        skill_source=Path("skills/waapi-skill"),
        expected_steps=linearized,
        expected_wwise_version="2022.1",
    )


def test_archived_broker_replay_preserves_declared_composer_setup_order() -> None:
    schema = ExpectedGatewayStep(
        "tx01.operation-schema",
        "operation-schema",
        ("audio.import",),
    )
    metadata = ExpectedGatewayStep(
        "tx01.metadata",
        "metadata",
        (
            "discover",
            "--object-type",
            "Sound",
            "--query",
            MetadataQueryArgument("volume"),
            "--limit",
            "8",
        ),
    )
    start = ExpectedGatewayStep(
        "tx01.draft-start",
        "draft-start",
        ("audio.import",),
    )
    action = ExpectedGatewayStep(
        "tx01.action.001",
        "draft-apply",
        (
            ResponseBinding(start.name, "/draft/draft_id"),
            "--task-authority",
            ResponseBinding(start.name, "/task_authority"),
            "--expected-revision",
            ResponseBinding(start.name, "/draft/revision"),
            "--compact",
            "--facts",
            DraftTypedActionArgument(
                {
                    "contract": "waapi-skill.operation-draft-action/v1",
                    "action": "set_import_option",
                    "name": "import_operation",
                    "value": "useExisting",
                },
                operation="audio.import",
            ),
        ),
    )
    canonical = (schema, metadata, start, action)
    setup_groups = ((metadata.name, start.name, action.name),)
    consumed_names = (schema.name, start.name, action.name, metadata.name)
    consumed = campaign._steps_in_consumed_order(canonical, consumed_names)

    replay = campaign._build_heavy_v3_broker_replay(
        skill_source=Path("skills/waapi-skill"),
        invocation_skill_source=Path("skills/waapi-skill"),
        canonical_steps=canonical,
        execution_steps=consumed,
        commutative_read_only_step_groups=(),
        commutative_composer_setup_step_groups=setup_groups,
        expected_wwise_version="2022.1",
        project_modification_policy="ask_before_changes",
    )

    assert tuple(step.name for step in replay.expected_steps) == tuple(
        step.name for step in canonical
    )
    assert tuple(step.name for step in replay._execution_steps) == consumed_names


def test_archived_broker_replay_rejects_undeclared_composer_interruption() -> None:
    schema = ExpectedGatewayStep(
        "tx01.operation-schema",
        "operation-schema",
        ("audio.import",),
    )
    metadata = ExpectedGatewayStep(
        "tx01.metadata",
        "metadata",
        ("discover", "--object-type", "Sound", "--limit", "8"),
    )
    start = ExpectedGatewayStep(
        "tx01.draft-start",
        "draft-start",
        ("audio.import",),
    )
    canonical = (schema, metadata, start)
    consumed = campaign._steps_in_consumed_order(
        canonical,
        (schema.name, start.name, metadata.name),
    )

    with pytest.raises(
        CampaignEvidenceError,
        match="undeclared protocol linearization",
    ):
        campaign._build_heavy_v3_broker_replay(
            skill_source=Path("skills/waapi-skill"),
            invocation_skill_source=Path("skills/waapi-skill"),
            canonical_steps=canonical,
            execution_steps=consumed,
            commutative_read_only_step_groups=(),
            commutative_composer_setup_step_groups=(),
            expected_wwise_version="2022.1",
            project_modification_policy="ask_before_changes",
        )


def test_archived_draft_action_preserves_submitted_json_spelling() -> None:
    action = campaign._archived_draft_action(
        (
            "draft-apply",
            "od1-draft",
            "--action-json",
            '{"contract":"waapi-skill.operation-draft-action/v1",'
            '"action":"set_property","value":0}',
        ),
        label="synthetic action",
    )

    assert action["value"] == 0
    assert type(action["value"]) is int


def test_archived_draft_action_reconstructs_legacy_typed_argv() -> None:
    expected = {
        "contract": "waapi-skill.operation-draft-action/v1",
        "action": "add_import_row",
        "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\雪",
        "audio_file": "/tmp/source with spaces.wav",
        "assignment": {"mode": "none"},
    }

    action = campaign._archived_draft_action(
        (
            "draft-apply",
            "od1-draft",
            "--compact",
            "--facts",
            "--action",
            "add_import_row",
            "--value",
            "object_path",
            "string",
            expected["object_path"],
            "--value",
            "audio_file",
            "string",
            expected["audio_file"],
            "--assignment",
            "none",
        ),
        label="synthetic typed action",
    )

    assert action == expected


def test_archived_draft_action_rejects_duplicate_json_keys() -> None:
    with pytest.raises(
        CampaignEvidenceError,
        match="Draft action argv is not strict JSON",
    ):
        campaign._archived_draft_action(
            (
                "draft-apply",
                "od1-draft",
                "--action-json",
                '{"action":"set_property","action":"remove_property"}',
            ),
            label="synthetic action",
        )


@dataclass(frozen=True, slots=True)
class _PrimaryDispatch:
    count: int = 1


@dataclass(frozen=True, slots=True)
class _VisibleInput:
    name: str
    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class _Scenario:
    id: str
    api: str
    prompt: str
    versions: tuple[str, ...] = ("2022.1",)
    item_type: str = "function"
    primary_dispatch: _PrimaryDispatch = _PrimaryDispatch()
    visible_inputs: tuple[Any, ...] = ()
    protocol: str = "direct"
    confirmation_prompt: str | None = None
    fixture: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.fixture is None:
            object.__setattr__(self, "fixture", {})

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    def render_prompt(self, values: Mapping[str, str]) -> str:
        expected = {item.name for item in self.visible_inputs}
        if set(values) != expected:
            raise ValueError("synthetic visible prompt input mismatch")
        return self.prompt.format_map(dict(values))

    @property
    def confirmation_turn_count(self) -> int:
        return self.primary_dispatch.count if self.protocol == "preview_confirm" else 0


@dataclass(frozen=True, slots=True)
class _Turn:
    index: int
    kind: str
    prompt: str


@dataclass(frozen=True, slots=True)
class _Unit:
    unit_id: str
    version: str
    scenario: _Scenario
    user_turn_count: int = 1
    transaction_count: int = 0

    @property
    def turns(self) -> tuple[_Turn, ...]:
        rows = [_Turn(1, "request", self.scenario.prompt)]
        rows.extend(
            _Turn(
                index,
                "confirmation",
                self.scenario.confirmation_prompt or "可以，按刚才的预览执行。",
            )
            for index in range(2, self.user_turn_count + 1)
        )
        return tuple(rows)


def _unit(index: int, *, version: str = "2022.1") -> _Unit:
    scenario_id = f"OBJ22-F-GET-{index:02d}"
    return _Unit(
        unit_id=scenario_id,
        version=version,
        scenario=_Scenario(
            scenario_id,
            "ak.wwise.core.object.get",
            f"synthetic natural request for {scenario_id}",
            versions=(version,),
        ),
    )


def _cli_unit(index: int, *, version: str = "2022.1") -> _Unit:
    return _cli_api_unit("ak.wwise.cli.migrate", index, version=version)


def _cli_api_unit(
    api: str,
    index: int,
    *,
    version: str = "2022.1",
) -> _Unit:
    reviewed = next(
        item
        for item in _suite_cli_cases()
        if item.api == api and item.scenario_index == index
    )
    return _Unit(
        unit_id=reviewed.id,
        version=version,
        scenario=_Scenario(
            reviewed.id,
            reviewed.api,
            f"synthetic natural request for {reviewed.id}",
            versions=(version,),
            protocol=reviewed.protocol,
            confirmation_prompt=reviewed.confirmation_prompt,
            fixture=reviewed.fixture,
        ),
        user_turn_count=1 + reviewed.confirmation_turn_count,
        transaction_count=1,
    )


def _soundbank_unit(
    scenario_id: str,
    api: str,
    *,
    primary_count: int,
) -> _Unit:
    asset_spec: Mapping[str, Any] = (
        {
            "soundbank": "Bank",
            "expected_after": ({"object": "Hero", "filters": ()},),
        }
        if api == "ak.wwise.core.soundbank.setInclusions"
        else {}
    )
    refusal = primary_count == 0
    topic = api == SOUNDBANK_TOPIC
    return _Unit(
        unit_id=scenario_id,
        version="2022.1",
        scenario=_Scenario(
            scenario_id,
            api,
            f"synthetic natural request for {scenario_id}",
            item_type="topic" if topic else "function",
            primary_dispatch=_PrimaryDispatch(primary_count),
            protocol="direct" if refusal or topic else "preview_confirm",
            confirmation_prompt=(
                None if refusal or topic else "可以，按刚才的预览执行。"
            ),
            fixture={"id": scenario_id, "api": api, "asset_spec": asset_spec},
        ),
        user_turn_count=1 if refusal or topic else 2,
        transaction_count=0 if refusal or topic else 1,
    )


def _multi_turn_unit(index: int, *, version: str = "2022.1") -> _Unit:
    scenario_id = f"OBJ22-F-CREATE-{index:02d}"
    return _Unit(
        unit_id=scenario_id,
        version=version,
        scenario=_Scenario(
            scenario_id,
            "ak.wwise.core.object.create",
            f"synthetic natural request for {scenario_id}",
            versions=(version,),
            protocol="preview_confirm",
            confirmation_prompt="可以，按刚才的预览执行。",
        ),
        user_turn_count=2,
        transaction_count=1,
    )


def _visible_request_unit(index: int, *, version: str = "2024.1") -> _Unit:
    scenario_id = f"VS24-F-AUDIO-CONVERT-{index:02d}"
    return _Unit(
        unit_id=scenario_id,
        version=version,
        scenario=_Scenario(
            scenario_id,
            "ak.wwise.core.audio.convert",
            "请把目标音频转换到 {io_root} 并汇总。",
            versions=(version,),
            visible_inputs=(
                _VisibleInput(
                    "io_root",
                    "absolute_directory_path",
                    "本次转换唯一允许写入的绝对目录",
                ),
            ),
            protocol="preview_confirm",
            confirmation_prompt="可以，按刚才的预览执行。",
        ),
        user_turn_count=2,
        transaction_count=1,
    )


def _visible_preview_only_request_unit(
    index: int,
    *,
    version: str = "2024.1",
) -> _Unit:
    unit = _visible_request_unit(index, version=version)
    return replace(
        unit,
        scenario=replace(
            unit.scenario,
            protocol="direct",
            confirmation_prompt=None,
            fixture={"synthetic_preview_only": True},
        ),
        user_turn_count=1,
        transaction_count=0,
    )


@functools.cache
def _synthetic_windows_powershell_core_host(
) -> WindowsPowerShellCoreHost | None:
    """Attest the one native Windows shell shared by synthetic campaign evidence."""

    if os.name != "nt":
        return None
    return discover_windows_powershell_core(platform_name="nt")


def _options(tmp_path: Path) -> campaign.CampaignOptions:
    skill = tmp_path / "skill"
    skill.mkdir(exist_ok=True)
    (skill / "SKILL.md").write_text("# synthetic skill\n", encoding="utf-8")
    references = skill / "references"
    references.mkdir()
    (references / "waapi-query.md").write_text(
        "# synthetic query lane\n",
        encoding="utf-8",
    )
    (references / "waapi-operate.md").write_text(
        "# synthetic operate lane\n",
        encoding="utf-8",
    )
    scripts = skill / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("# synthetic packaged runner\n", encoding="utf-8")
    (scripts / "gateway.py").write_text("# synthetic gateway\n", encoding="utf-8")
    suite = tmp_path / "suite-v3.json"
    suite.write_text("{}\n", encoding="utf-8")
    codex = (
        tmp_path / "codex-release" / "bin" / "codex.exe"
        if os.name == "nt"
        else tmp_path / "codex"
    )
    codex.parent.mkdir(parents=True, exist_ok=True)
    codex.write_text("synthetic codex binary\n", encoding="utf-8")
    codex.chmod(0o755)
    if os.name == "nt":
        release = codex.parent.parent
        (release / "codex-package.json").write_text(
            '{"version":"1.2.3"}\n',
            encoding="utf-8",
        )
        for helper in (
            release / "bin" / "codex-code-mode-host.exe",
            release / "codex-path" / "rg.exe",
            release / "codex-resources" / "codex-command-runner.exe",
            release / "codex-resources" / "codex-windows-sandbox-setup.exe",
        ):
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("synthetic helper\n", encoding="utf-8")
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    versions: dict[str, dict[str, str]] = {}
    for version in ("2022.1", "2024.1", "2025.1"):
        version_root = tmp_path / "live-fixture" / version
        version_root.mkdir(parents=True)
        console = version_root / "WwiseConsole.sh"
        console.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        console.chmod(0o755)
        project = version_root / "SampleProject.wproj"
        project.write_text(f"<WwiseDocument version='{version}'/>\n", encoding="utf-8")
        (version_root / "Actor-Mixer Hierarchy").mkdir()
        (version_root / "Actor-Mixer Hierarchy" / "Default Work Unit.wwu").write_text(
            f"<WorkUnit version='{version}'/>\n",
            encoding="utf-8",
        )
        versions[version] = {
            "wwise_console": str(console),
            "sample_project": str(project),
            "sandbox_root": str(tmp_path / "sandboxes" / version),
        }
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"versions": versions}) + "\n", encoding="utf-8")
    return campaign.CampaignOptions(
        campaign_root=tmp_path / "workspace" / "heavy-campaign",
        resume=False,
        verify_only=False,
        profile=campaign.HEAVY_V3_PROFILE_ID,
        suite_path=suite.resolve(),
        skill_source=skill.resolve(),
        codex_binary=codex.resolve(),
        auth_json=auth.resolve(),
        live_config=live.resolve(),
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=90.0,
        case_ids=(),
        versions=(),
        pair_ids=(),
        offline_only=False,
        lock_timeout_seconds=1.0,
        max_pre_action_retries=0,
        windows_powershell_core_host=_synthetic_windows_powershell_core_host(),
    )


def _matrix_options(
    options: campaign.CampaignOptions,
    units: Sequence[_Unit],
    root: Path,
) -> matrix.RunnerOptions:
    return matrix.RunnerOptions(
        profile=matrix.HEAVY_V3_PROFILE_ID,
        iteration_root=root,
        suite_path=options.suite_path,
        skill_source=options.skill_source,
        codex_binary=options.codex_binary,
        auth_json=options.auth_json,
        live_config=options.live_config,
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier,
        timeout_seconds=options.timeout_seconds,
        case_ids=tuple(unit.unit_id for unit in units),
        versions=(),
        pair_ids=(),
        offline_only=False,
        overwrite=False,
        windows_powershell_core_host=options.windows_powershell_core_host,
    )


def _write_matrix_evidence(
    root: Path,
    *,
    options: campaign.CampaignOptions,
    units: Sequence[_Unit],
    statuses: Sequence[str],
    terminal: bool = True,
    preflight: str = "passed",
    stop_reason: str = "",
    run_errors: Sequence[str] = (),
    visible_values_by_id: Mapping[str, Mapping[str, str]] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=False)
    selected_rows = tuple(
        campaign.heavy_v3_unit_row(unit, sequence=index)
        for index, unit in enumerate(units, start=1)
    )
    records: list[dict[str, Any]] = []
    for index, status in enumerate(statuses, start=1):
        unit = units[index - 1]
        row = selected_rows[index - 1]
        scenario_root = root / "scenarios" / f"{index:03d}-{unit.unit_id}"
        scenario_root.mkdir(parents=True)
        reason = "" if status == "PASS" else f"synthetic {status.lower()}"
        if status == "PASS":
            outcome = _write_passing_project_outcome(
                scenario_root,
                unit=unit,
                thread_id=f"thread-{index}",
                options=options,
                visible_values=(visible_values_by_id or {}).get(unit.unit_id, {}),
            )
        else:
            task_root = scenario_root / "evidence" / "codex-task"
            task_root.mkdir(parents=True)
            (task_root / "agent-workspace").mkdir()
            _write_prompt_materialization(
                task_root,
                unit=unit,
                visible_values=(visible_values_by_id or {}).get(unit.unit_id, {}),
            )
            outcome = {
                "contract": (
                    campaign.HEAVY_V3_CLI_OUTCOME_CONTRACT
                    if row["runner"] == "cli"
                    else campaign.HEAVY_V3_PROJECT_OUTCOME_CONTRACT
                ),
                "scenario_id": unit.unit_id,
                "version": unit.version,
                "status": status,
                "reason": reason,
                "scenario_root": str(scenario_root.resolve()),
                "task_root": str(task_root.resolve()),
                "thread_id": None,
                "checks": {"synthetic_failure": True},
                "lifecycle": None,
            }
        record = {
            "contract": matrix.HEAVY_V3_CASE_RECORD_CONTRACT,
            **row,
            "status": status,
            "reason": reason,
            "scenario_root": str(scenario_root.resolve()),
            "runner_outcome": outcome,
        }
        matrix.write_json(scenario_root / "outcome.json", outcome)
        matrix.write_json(scenario_root / "matrix-case.json", record)
        records.append(record)

    started = "2026-07-20T00:00:00Z"
    completed = "2026-07-20T00:01:00Z" if terminal else None
    matrix_options = _matrix_options(options, units, root)
    run_config = matrix._heavy_v3_run_config(
        matrix_options,
        unit_rows=selected_rows,
        records=records,
        run_errors=run_errors,
        stop_reason=stop_reason,
        preflight_state=preflight,
        started_at=started,
        completed_at=completed,
    )
    summary = matrix._heavy_v3_summary(
        unit_rows=selected_rows,
        records=records,
        run_errors=run_errors,
        stop_reason=stop_reason,
        preflight_state=preflight,
        started_at=started,
        completed_at=completed,
    )
    matrix.write_json(root / "run-config.json", run_config)
    matrix.write_json(root / "summary.json", summary)
    matrix.write_json(
        root / "live-preflight.json",
        (
            {
                "contract": campaign.HEAVY_V3_LIVE_PREFLIGHT_CONTRACT,
                "ok": True,
                "dependency": "waapi-client",
                "module": "waapi",
                "required_symbols": ["WaapiClient", "WaapiRequestFailed"],
                "current_interpreter": str(Path(sys.executable).resolve(strict=False)),
                "automatic_install_attempted": False,
            }
            if preflight == "passed"
            else {
                "contract": campaign.HEAVY_V3_LIVE_PREFLIGHT_CONTRACT,
                "ok": False,
                "error": {"type": "SyntheticPreflight", "message": "blocked"},
            }
        ),
    )


def _mark_codex_infrastructure_block(
    root: Path,
    *,
    options: campaign.CampaignOptions,
    unit: _Unit,
    sequence: int,
    category: str,
    failed_turn_index: int = 1,
) -> None:
    scenario_root = root / "scenarios" / f"{sequence:03d}-{unit.unit_id}"
    outcome_path = scenario_root / "outcome.json"
    case_path = scenario_root / "matrix-case.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    matrix_case = json.loads(case_path.read_text(encoding="utf-8"))
    infrastructure_message = {
        "quota_or_rate_limit": "rate limit exceeded",
        "authentication": "authentication failed",
        "service_unavailable": "service unavailable",
        "timeout_before_agent_action": "Codex CLI timed out before any agent action",
        "turn_failed_before_agent_action": "synthetic turn failed",
    }[category]
    reason = (
        "CodexInfrastructureError: Codex CLI infrastructure failure "
        f"({category}): {infrastructure_message}"
    )
    source_hash = {
        "algorithm": "sha256",
        "strategy": "full",
        "digest": "d" * 64,
        "file_count": 2,
        "bytes_hashed": 100,
    }
    evidence_root = scenario_root / "evidence"
    evidence_root.mkdir(exist_ok=True)
    task_root = evidence_root / "codex-task"
    if task_root.exists():
        prompt_materialization = (
            task_root / campaign.HEAVY_V3_PROMPT_MATERIALIZATION_FILE
        )
        provenance = read_prompt_provenance(
            evidence_root / campaign.HEAVY_V3_PROMPT_PROVENANCE_FILE,
            scenario=unit.scenario,  # type: ignore[arg-type]
            version=unit.version,
            scenario_root=scenario_root,
            require_paths=False,
        )
    else:
        task_root.mkdir()
        (task_root / "agent-workspace").mkdir()
        prompt_materialization, provenance, _business_oracle_plan = (
            _write_prompt_materialization(
                task_root,
                unit=unit,
            )
        )
    workspace = task_root / "agent-workspace"
    skill_install = workspace_skill_install_path(workspace)
    if not skill_install.exists() and not skill_install.is_symlink():
        skill_install = prepare_workspace_skill_install(
            workspace,
            options.skill_source,
            platform_name=(
                "nt"
                if options.windows_powershell_core_host is not None
                else "posix"
            ),
        )
    expected_prompts = provenance.prompts
    protocol = provenance.protocol
    broker_state = task_root / "broker" / "state"
    broker_evidence_root = task_root / "broker" / "evidence"
    broker_state.mkdir(parents=True)
    broker_evidence_root.mkdir()
    broker_records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version=unit.version,
        invocation_skill_source=skill_install,
    )
    if not 1 <= failed_turn_index <= unit.user_turn_count:
        raise AssertionError("synthetic failed turn must be inside the unit topology")
    prior_thread_id = "thread-prior" if failed_turn_index > 1 else None
    previous_prefix = 0
    for prior_index in range(1, failed_turn_index):
        prior_prompt = expected_prompts[prior_index - 1]
        prior_prompt_sha256 = hashlib.sha256(
            prior_prompt.encode("utf-8")
        ).hexdigest()
        prior_turn_root = task_root / "turns" / f"turn-{prior_index:02d}"
        prior_turn_root.mkdir(parents=True)
        prefix = protocol.turn_prefix_counts[prior_index - 1]
        prior_grade = {
            "index": prior_index,
            "prompt_sha256": prior_prompt_sha256,
            "broker_prefix_count": prefix,
            "reconciliation": {
                "passed": True,
                "observed_command_count": prefix,
                "accepted_record_count": prefix,
                "errors": [],
            },
            "common_gates": {
                key: True for key in campaign._HEAVY_V3_REQUIRED_COMMON_GATES
            },
            "errors": [],
            "passed": True,
        }
        matrix.write_text(prior_turn_root / "prompt.txt", prior_prompt + "\n")
        prior_events = _synthetic_events(
            thread_id=str(prior_thread_id),
            records=broker_records[previous_prefix:prefix],
            final_response="预览已准备。",
            read_paths=(
                _synthetic_first_turn_reads(
                    options,
                    unit,
                    skill_source=_synthetic_runtime_skill_read_source(
                        options,
                        skill_install,
                    ),
                )
                if prior_index == 1
                else ()
            ),
            windows_skill_read_source=(
                skill_install
                if options.windows_powershell_core_host is not None
                else None
            ),
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
        matrix.write_text(prior_turn_root / "events.jsonl", prior_events)
        matrix.write_text(prior_turn_root / "stderr.txt", "")
        matrix.write_text(prior_turn_root / "final.txt", "预览已准备。\n")
        matrix.write_json(prior_turn_root / "turn-grade.json", prior_grade)
        matrix.write_json(
            prior_turn_root / "codex-facts.json",
            _synthetic_codex_facts(
                options=options,
                task_root=task_root,
                turn_root=prior_turn_root,
                turn_index=prior_index,
                prompt=prior_prompt,
                thread_id=str(prior_thread_id),
                events_text=prior_events,
                protocol=protocol,
                version=unit.version,
            ),
        )
        previous_prefix = prefix
    failed_turn_root = (
        task_root / "turns" / f"turn-{failed_turn_index:02d}"
    )
    failed_turn_root.mkdir(parents=True)
    failed_prompt = expected_prompts[failed_turn_index - 1]
    prompt_sha256 = hashlib.sha256(failed_prompt.encode("utf-8")).hexdigest()
    failed_thread_id = prior_thread_id or "thread-failed"
    failed_events = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
        for item in (
            {"type": "thread.started", "thread_id": failed_thread_id},
            {"type": "turn.started"},
            {
                "type": "turn.failed",
                "error": {"message": infrastructure_message},
            },
        )
    )
    failed_facts = _synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=failed_turn_root,
        turn_index=failed_turn_index,
        prompt=failed_prompt,
        thread_id=failed_thread_id,
        events_text=failed_events,
        protocol=protocol,
        version=unit.version,
        exit_status=1,
    )
    matrix.write_text(failed_turn_root / "prompt.txt", failed_prompt + "\n")
    matrix.write_text(failed_turn_root / "events.jsonl", failed_events)
    matrix.write_text(
        failed_turn_root / "stderr.txt", infrastructure_message + "\n"
    )
    matrix.write_text(failed_turn_root / "final.txt", "\n")
    matrix.write_json(failed_turn_root / "codex-facts.json", failed_facts)
    expected_step_names = [step.name for step in protocol.steps]
    prior_prefix = previous_prefix
    failed_prefix = protocol.turn_prefix_counts[failed_turn_index - 1]
    broker_payload = {
        "expected_step_names": expected_step_names,
        "consumed_step_names": expected_step_names[:prior_prefix],
        "records": broker_records[:prior_prefix],
        "state_directory": str(broker_state),
        "evidence_directory": str(broker_evidence_root),
        "runner_path": str(options.skill_source / "scripts" / "run.py"),
        "terminal_state": "RUNNING",
        "complete": False,
        "passed": False,
    }
    matrix.write_json(task_root / "broker-evidence.json", broker_payload)
    artifact_paths = (
        prompt_materialization,
        failed_turn_root / "prompt.txt",
        failed_turn_root / "events.jsonl",
        failed_turn_root / "stderr.txt",
        failed_turn_root / "final.txt",
        failed_turn_root / "codex-facts.json",
        task_root / "broker-evidence.json",
    )
    task_failure = {
        "contract": campaign.HEAVY_V3_TASK_INFRASTRUCTURE_FAILURE_CONTRACT,
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "failed_turn_index": failed_turn_index,
        "expected_turn_count": unit.user_turn_count,
        "prior_completed_turn_count": failed_turn_index - 1,
        "previous_broker_prefix": prior_prefix,
        "expected_failed_turn_prefix": failed_prefix,
        "prior_thread_id": prior_thread_id,
        "prompt_sha256": prompt_sha256,
        "failure": {
            "category": category,
            "turn_failed": True,
            "timed_out": False,
            "agent_item_event_count": 0,
        },
        "artifact_sha256": {
            path.relative_to(task_root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in artifact_paths
        },
    }
    matrix.write_json(task_root / "infrastructure-failure.json", task_failure)
    owned_root = scenario_root / "owned"
    owned_root.mkdir(exist_ok=True)
    quarantine_path = evidence_root / "quarantine.json"
    runner = matrix_case["runner"]
    if runner == "cli":
        case_root = owned_root / "case"
        control_project = case_root / "business-host" / "SampleProject.wproj"
        control_project.parent.mkdir(parents=True)
        control_project.write_text("<WwiseDocument/>\n", encoding="utf-8")
        empty_sha256 = hashlib.sha256(b"").hexdigest()
        lifecycle = {
            "contract": campaign.HEAVY_V3_CLI_LIFECYCLE_CONTRACT,
            "requested_status": "BLOCKED",
            "final_status": "BLOCKED",
            "owned_state_retained": True,
            "source_hash_before": source_hash,
            "source_hash_after": source_hash,
            "source_mtime_before_ns": 123456,
            "source_mtime_after_ns": 123456,
            "phases": [
                {
                    "evidence": {
                        "role": "business",
                        "argv": [
                            "/synthetic/WwiseConsole",
                            "waapi-server",
                            str(control_project),
                        ],
                        "cwd": str(case_root),
                        "shell": False,
                        "started": True,
                        "ready": True,
                        "process_exited": True,
                        "residual_pids": [],
                        "shutdown_error": None,
                        "open_project_path": str(control_project),
                        "returncode": 0,
                        "natural_exit_before_shutdown": False,
                        "runner_shutdown_requested": True,
                    },
                    "stdout_sha256": empty_sha256,
                    "stderr_sha256": empty_sha256,
                    "log_overflow": False,
                    "ready_version": "2022.1",
                }
            ],
            "errors": [],
            "quarantine_path": str(quarantine_path.resolve()),
        }
        quarantine = {
            "contract": campaign.HEAVY_V3_CLI_LIFECYCLE_CONTRACT,
            "status": "BLOCKED",
            "owned_root": str(owned_root),
            "owned_tree_sha256": stable_tree_sha256(owned_root),
            "never_reuse": True,
        }
    else:
        sandbox_project = owned_root / "sandbox-root" / "SampleProject.wproj"
        sandbox_project.parent.mkdir()
        sandbox_project.write_text("<WwiseDocument/>\n", encoding="utf-8")
        lifecycle = {
            "contract": campaign.HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT,
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "requested_status": "BLOCKED",
            "final_status": "BLOCKED",
            "sandbox_retained": True,
            "source_hash_before": source_hash,
            "source_hash_after": source_hash,
            "source_mtime_before_ns": 123456,
            "source_mtime_after_ns": 123456,
            "errors": [f"scenario:{reason}"],
            "quarantine_path": str(quarantine_path.resolve()),
        }
        matrix.write_json(
            evidence_root / "start.json",
            {
                "contract": campaign.HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT,
                "scenario_id": unit.unit_id,
                "version": unit.version,
                "started_at": "2026-07-20T00:00:00Z",
                "source_hash_before": source_hash,
                "source_mtime_before_ns": 123456,
                "sandbox_project": str(sandbox_project),
                "launch_cwd": str(sandbox_project.parent),
                "endpoint": {"host": "127.0.0.1", "port": 18080},
                "isolated_launch_environment": {},
                "owned_wine_prefix": None,
            },
        )
        quarantine = {
            "contract": campaign.HEAVY_V3_PROJECT_QUARANTINE_CONTRACT,
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "status": "BLOCKED",
            "sealed_at": "2026-07-20T00:01:00Z",
            "owned_root": str(owned_root),
            "owned_tree_sha256": stable_tree_sha256(owned_root),
            "never_reuse": True,
            "errors": [f"scenario:{reason}"],
        }
    matrix.write_json(quarantine_path, quarantine)
    outcome.update(
        {
            "status": "BLOCKED",
            "reason": reason,
            "thread_id": None,
            "task_root": str(task_root),
            "contract": (
                campaign.HEAVY_V3_CLI_OUTCOME_CONTRACT
                if runner == "cli"
                else campaign.HEAVY_V3_PROJECT_OUTCOME_CONTRACT
            ),
            "checks": {
                "failure_classification": "BLOCKED",
                "codex_infrastructure_failure": {
                    "category": category,
                    "turn_failed": True,
                    "timed_out": False,
                    "agent_item_event_count": 0,
                },
            },
            "lifecycle": lifecycle,
        }
    )
    if runner == "project":
        outcome["checks"]["direct_client_closed"] = True
    matrix_case.update(
        {
            "status": "BLOCKED",
            "reason": reason,
            "runner_outcome": outcome,
        }
    )
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["case_records"][sequence - 1]["reason"] = reason
    matrix.write_json(evidence_root / "lifecycle.json", lifecycle)
    matrix.write_json(outcome_path, outcome)
    matrix.write_json(case_path, matrix_case)
    matrix.write_json(summary_path, summary)


def _persist_runner_outcome(scenario_root: Path, outcome: Mapping[str, Any]) -> None:
    outcome_path = scenario_root / "outcome.json"
    case_path = scenario_root / "matrix-case.json"
    matrix_case = json.loads(case_path.read_text(encoding="utf-8"))
    matrix_case["runner_outcome"] = dict(outcome)
    matrix.write_json(outcome_path, outcome)
    matrix.write_json(case_path, matrix_case)


def _mark_pre_materialization_block(
    root: Path,
    *,
    unit: _Unit,
    sequence: int,
    reason: str = "SyntheticFixtureError: fixture preparation failed",
) -> None:
    """Turn one synthetic row into a runner block before any Codex plan exists."""

    scenario_root = root / "scenarios" / f"{sequence:03d}-{unit.unit_id}"
    evidence_root = scenario_root / "evidence"
    task_root = evidence_root / "codex-task"
    if task_root.exists():
        shutil.rmtree(task_root)
    for path in (
        evidence_root / campaign.HEAVY_V3_PROMPT_PROVENANCE_FILE,
        evidence_root / campaign.BUSINESS_ORACLE_PLAN_FILE,
    ):
        if path.exists():
            path.unlink()

    outcome_path = scenario_root / "outcome.json"
    case_path = scenario_root / "matrix-case.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    outcome.update(
        {
            "status": "BLOCKED",
            "reason": reason,
            "task_root": None,
            "thread_id": None,
            "checks": {
                "exception": reason,
                "failure_classification": "BLOCKED",
            },
        }
    )
    matrix_case = json.loads(case_path.read_text(encoding="utf-8"))
    matrix_case.update(
        {
            "status": "BLOCKED",
            "reason": reason,
            "runner_outcome": outcome,
        }
    )
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["case_records"][sequence - 1]["reason"] = reason
    matrix.write_json(outcome_path, outcome)
    matrix.write_json(case_path, matrix_case)
    matrix.write_json(summary_path, summary)


def _materialized_prompts(
    unit: _Unit,
    *,
    visible_values: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    return (
        unit.scenario.render_prompt(dict(visible_values or {})),
        *(turn.prompt for turn in unit.turns[1:]),
    )


def _synthetic_typed_sections(
    unit: _Unit,
    *,
    protocol: V3GatewayProtocol,
    scenario_root: Path,
):
    if unit.scenario.api in {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }:
        recipe = build_object_heavy_v3_recipe(unit.unit_id)
        before = _synthetic_object_before(recipe)
        audio_root = scenario_root / "owned" / "assets" / "object-query-audio"
        manifest: list[dict[str, Any]] = []
        for item in recipe.fixture.objects:
            if item.object_type != "Sound" or item.source_language is None:
                continue
            audio_root.mkdir(parents=True, exist_ok=True)
            path = audio_root / f"{item.key}.wav"
            payload = f"synthetic-object-audio:{item.key}".encode("utf-8")
            path.write_bytes(payload)
            manifest.append(
                {
                    "key": item.key,
                    "path": str(path.resolve()),
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        return compile_object_business_plan(
            unit.scenario,
            recipe,
            protocol,
            before,
            manifest,
        )
    if unit.scenario.api == "ak.wwise.core.audio.convert":
        plan, before = _synthetic_audio_plan_and_before(unit, scenario_root)
        compile_protocol = (
            build_transaction_protocol((plan.operation_request,))
            if unit.scenario.fixture.get("synthetic_preview_only") is True
            else protocol
        )
        return compile_audio_conversion_business_plan(
            plan,
            before,
            compile_protocol,
            reviewed_scenario_fixture=unit.scenario.fixture,
        )
    return None


def _synthetic_protocol_and_typed_sections(
    unit: _Unit,
    *,
    scenario_root: Path,
    visible_values: Mapping[str, str],
):
    api = unit.scenario.api
    if api in {
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
        SOUNDBANK_TOPIC,
    }:
        materialized, before, protocol = _build_soundbank_case(
            api,
            unit.unit_id,
            scenario_root / "owned",
            refusal=unit.scenario.primary_dispatch.count == 0,
            topic=api == SOUNDBANK_TOPIC,
        )
        return (
            protocol,
            compile_soundbank_business_plan(materialized, before, protocol),
        )
    if api in {
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.migrate",
    }:
        runtime_root = scenario_root / "owned" / "cli-runtime"
        _plan, runtime, backend = _build_cli_runtime(unit.scenario, runtime_root)
        _seal_cli_runtime(
            runtime,
            backend,
            _make_cli_console(runtime_root),
            31100,
        )
        protocol = runtime.gateway_protocol()
        return protocol, compile_cli_business_plan(runtime, protocol)
    protocol = _synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values=visible_values,
    )
    return protocol, _synthetic_typed_sections(
        unit,
        protocol=protocol,
        scenario_root=scenario_root,
    )


def _synthetic_object_before(
    recipe: Any,
    *,
    set03_child_override_output: bool = False,
) -> ObjectRuntimeSnapshot:
    keys = [item.key for item in recipe.fixture.objects]
    ids = {
        key: f"{{00000000-0000-0000-0000-{index:012d}}}"
        for index, key in enumerate(keys, start=1)
    }
    paths = {item.path: ids[item.key] for item in recipe.fixture.objects}
    objects: list[MaterializedObject] = []
    for index, item in enumerate(recipe.fixture.objects, start=1):
        children_count = sum(
            candidate.parent_path == item.path
            for candidate in recipe.fixture.objects
        )
        properties = item.properties
        references = item.references
        if (
            recipe.scenario_id == "OBJ22-F-SET-03"
            and item.key.endswith("_child")
        ):
            parent = recipe.fixture.object(item.key.removesuffix("_child"))
            properties = parent.properties
            references = parent.references
        objects.append(
            MaterializedObject(
                key=item.key,
                id=ids[item.key],
                name=item.name,
                type=item.object_type,
                path=item.path,
                parent_id=paths.get(
                    item.parent_path,
                    "{99999999-9999-9999-9999-999999999999}",
                ),
                notes=item.notes,
                properties=tuple(
                    ObjectProperty(prop.name, prop.value)
                    for prop in properties
                ),
                references=tuple(
                    MaterializedReference(ref.name, ids[ref.target_key])
                    for ref in references
                ),
                source_language=item.source_language,
                is_included=item.is_included,
                children_count=children_count,
                active_source_id=(
                    f"{{10000000-0000-0000-0000-{index:012d}}}"
                    if item.source_language is not None
                    else None
                ),
                active_source_name=(
                    item.key if item.source_language is not None else None
                ),
                active_source_path=(
                    f"{item.path}\\{item.key}"
                    if item.source_language is not None
                    else None
                ),
            )
        )
    absent = tuple(recipe.fixture.absent_paths)
    prefixes = tuple(
        (f"{parent}|{prefix}", ())
        for parent, prefix in recipe.fixture.absent_sibling_prefixes
    )
    override_output_rows = tuple(
        (
            item.key,
            (
                (
                    set03_child_override_output
                    if recipe.scenario_id == "OBJ22-F-SET-03"
                    and item.key.endswith("_child")
                    else any(
                        reference.name == "OutputBus"
                        for reference in item.references
                    )
                )
                if item.object_type
                in {"ActorMixer", "RandomSequenceContainer", "Sound"}
                else None
            ),
        )
        for item in recipe.fixture.objects
    )
    digest = campaign._canonical_sha256(
        {
            "objects": [asdict(item) for item in objects],
            "absent_paths": list(absent),
            "sibling_prefix_rows": [
                [label, list(rows)] for label, rows in prefixes
            ],
            "override_output_rows": [list(row) for row in override_output_rows],
        }
    )
    return ObjectRuntimeSnapshot(
        tuple(objects),
        absent,
        prefixes,
        digest,
        override_output_rows,
    )


def _synthetic_audio_components_and_profiles(scenario_id: str):
    presets = (
        ConversionPreset(
            "synthetic", "SyntheticConversionComponent", "PCM", 48000, 1
        ),
    )
    profiles = derive_conversion_profiles(
        scenario_id=scenario_id,
        platforms=("Windows",),
        presets=presets,
        settings_maps=((("Windows", "synthetic"),),),
    )
    return presets, profiles


def _synthetic_audio_plan_and_before(
    unit: _Unit,
    scenario_root: Path,
) -> tuple[AudioConversionPlan, AudioConversionSnapshot]:
    io_root = scenario_root / "owned" / "io"
    sandbox_root = scenario_root / "owned" / "project"
    asset_root = scenario_root / "owned" / "assets"
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Synthetic"
    operation_request = _synthetic_audio_operation_request(unit, io_root=io_root)
    presets, profiles = _synthetic_audio_components_and_profiles(unit.unit_id)
    original = FileState(
        str(asset_root / "synthetic.wav"),
        True,
        64,
        "1" * 64,
        1,
    )
    converted = FileState(
        str(io_root / "Windows" / "synthetic.wem"),
        True,
        32,
        "2" * 64,
        10,
    )
    conversion_xml = FileState(
        str(sandbox_root / "Conversion Settings.wwu"),
        True,
        16,
        "3" * 64,
        1,
    )
    artifact = ConvertedArtifact(
        object_path=object_path,
        object_id="{11111111-1111-1111-1111-111111111111}",
        source_id="{33333333-3333-3333-3333-333333333333}",
        source_key="synthetic",
        platform="Windows",
        language="SFX",
        conversion_id="{44444444-4444-4444-4444-444444444444}",
        conversion_name=profiles[0].name,
        original_path=original.path,
        original_file=original,
        converted_path=converted.path,
        file=converted,
        codec="PCM",
        sample_rate=48000,
    )
    snapshot_value = {
        "artifacts": [
            asdict(
                replace(
                    artifact,
                    file=FileState(converted.path, False, None, None, None),
                    codec=None,
                    sample_rate=None,
                )
            )
        ],
        "baseline_artifacts": [asdict(artifact)],
        "inputs": [asdict(original)],
        "originals": [asdict(original)],
        "authoring_files": [],
        "conversion_xml": asdict(conversion_xml),
        # The synthetic case models the ordinary conversion fixture after its
        # target cache file has been removed for the tested dispatch.  The
        # full pre-removal artifact remains sealed in baseline_artifacts, but
        # it is no longer part of the current stable output tree.
        "output_tree": [],
        "baseline_artifact_paths": [converted.path],
    }
    before = AudioConversionSnapshot(
        artifacts=(
            replace(
                artifact,
                file=FileState(converted.path, False, None, None, None),
                codec=None,
                sample_rate=None,
            ),
        ),
        baseline_artifacts=(artifact,),
        input_files=(original,),
        originals_files=(original,),
        authoring_files=(),
        conversion_xml=conversion_xml,
        output_tree=(),
        baseline_artifact_paths=(converted.path,),
        volatile_cache_files=tuple(
            VolatileFileState(path, False, None)
            for path in audio_conversion_volatile_cache_paths(io_root)
        ),
        digest=campaign._canonical_sha256(snapshot_value),
    )
    plan = AudioConversionPlan(
        scenario_id=unit.unit_id,
        sandbox_project=sandbox_root / "SampleProject.wproj",
        sandbox_root=sandbox_root,
        asset_root=asset_root,
        io_root=io_root,
        objects=(object_path,),
        platforms=("Windows",),
        languages=("SFX",),
        presets=presets,
        profiles=profiles,
        bindings=(
            ConversionBinding(
                object_path,
                (("SFX", "synthetic"),),
                (("Windows", "synthetic"),),
                False,
            ),
        ),
        wav_filename_pattern="{key}.wav",
        source_seeds_by_key=(("synthetic", "seed"),),
        initial_settings_by_path=((object_path, (("Windows", "synthetic"),)),),
        source_delta=None,
        setting_delta=None,
        missing_cache_paths=(),
        operation_request=operation_request,
        expected_output_count=1,
    )
    return plan, before


def _write_prompt_materialization(
    task_root: Path,
    *,
    unit: _Unit,
    visible_values: Mapping[str, str] | None = None,
) -> tuple[Path, PromptProvenanceEvidence, BusinessOraclePlanEvidence]:
    sealed_visible_values = dict(visible_values or {})
    prompts = _materialized_prompts(unit, visible_values=sealed_visible_values)
    scenario_root = task_root.parents[1]
    (scenario_root / "owned").mkdir(exist_ok=True)
    protocol, typed_sections = _synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=scenario_root,
        visible_values=sealed_visible_values,
    )
    provenance = write_prompt_provenance(
        scenario=unit.scenario,  # type: ignore[arg-type]
        version=unit.version,
        scenario_root=scenario_root,
        prompts=prompts,
        visible_values=sealed_visible_values,
        protocol=protocol,
    )
    if typed_sections is not None:
        family_kwargs = typed_sections.writer_kwargs()
    else:
        fixture_value = json.loads(
            json.dumps(
                unit.scenario.fixture,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
        )
        fixture_sha256 = hashlib.sha256(
            json.dumps(
                fixture_value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        primary_steps = [
            step.name
            for step in protocol.steps
            if step.subcommand
            in {"call", "query-object", "wait-topic", "execute"}
        ]
        family_kwargs = {
            "fixture_spec": {
                "kind": "scenario_fixture",
                "sha256": fixture_sha256,
            },
            "payload_bindings": {
                "primary_steps": (
                    primary_steps
                    if unit.scenario.primary_dispatch.count > 0
                    else []
                ),
                "verification_steps": [
                    step.name
                    for step in protocol.steps
                    if step.subcommand
                    in {"call", "query-object", "wait-topic", "verify"}
                    or step.terminal_execute
                    or step.allowed_exit_codes == (2,)
                ],
            },
            "assertion_ids": ("common.synthetic-campaign",),
            "static_expectation": {"scenario_fixture": fixture_value},
            "live_binding": {},
            "delta_rules": (),
        }
    business_oracle_plan = write_business_oracle_plan(
        scenario_id=unit.unit_id,
        version=unit.version,
        api=unit.scenario.api,
        runner="cli" if unit.scenario.api.startswith("ak.wwise.cli.") else "project",
        family=business_family_for_api(unit.scenario.api),
        scenario_root=scenario_root,
        protocol_sha256=provenance.payload["protocol"]["sha256"],
        provenance_sha256=provenance.sha256,
        primary_dispatch_count=unit.scenario.primary_dispatch.count,
        **family_kwargs,
    )
    path = task_root / campaign.HEAVY_V3_PROMPT_MATERIALIZATION_FILE
    matrix.write_json(
        path,
        prompt_materialization_receipt(
            provenance,
            business_oracle_plan=business_oracle_plan,
        ),
    )
    return path, provenance, business_oracle_plan


def _direct_typed_provenance(
    scenario: Any,
    *,
    version: str,
    scenario_root: Path,
    protocol: V3GatewayProtocol,
    visible_values: Mapping[str, str],
) -> PromptProvenanceEvidence:
    scenario_root.mkdir(parents=True, exist_ok=True)
    (scenario_root / "owned").mkdir(exist_ok=True)
    (scenario_root / "evidence").mkdir(exist_ok=True)
    prompts = [scenario.render_prompt(visible_values)]
    prompts.extend(
        scenario.confirmation_prompt
        for _index in range(scenario.confirmation_turn_count)
    )
    return write_prompt_provenance(
        scenario=scenario,
        version=version,
        scenario_root=scenario_root,
        prompts=tuple(prompts),
        visible_values=visible_values,
        protocol=protocol,
    )


def _synthetic_protocol(
    unit: _Unit,
    *,
    scenario_root: Path,
    visible_values: Mapping[str, str],
) -> V3GatewayProtocol:
    api = unit.scenario.api
    if api in {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
    }:
        recipe = build_object_heavy_v3_recipe(unit.unit_id)
        if isinstance(recipe.request, OperationRequestSpec):
            return build_transaction_protocol((recipe.request.as_dict(),))
        if isinstance(recipe.request, QueryObjectRequestSpec):
            return build_direct_protocol(
                [
                    query_schema_step(),
                    query_object_step("query-object", recipe.request.argv[3:]),
                ]
            )
        raise AssertionError("synthetic object recipe request is not closed")
    if api == "ak.wwise.core.audio.convert":
        io_root = scenario_root / "owned" / "io"
        io_root.mkdir(parents=True, exist_ok=True)
        if visible_values.get("io_root") != str(io_root):
            raise ValueError("synthetic audio io_root must be scenario_root/owned/io")
        request = _synthetic_audio_operation_request(unit, io_root=io_root)
        if unit.scenario.fixture.get("synthetic_preview_only") is not True:
            return build_transaction_protocol((request,))
        complete = build_transaction_protocol((request,))
        preview_index = next(
            index
            for index, step in enumerate(complete.steps)
            if step.subcommand in {"typed-call", "typed-operation", "preview-from-draft"}
        )
        # Keep a deliberately incomplete lifecycle for the tamper test while
        # still using the normal typed construction path.  The oracle must
        # reject the missing execute/verify phases, not rely on retired JSON.
        return V3GatewayProtocol(
            complete.steps[: preview_index + 1],
            (preview_index + 1,),
        )
    steps = tuple(
        ExpectedGatewayStep(
            name=f"synthetic-step-{index}",
            subcommand="call",
            arguments=(
                api,
                "--args-json",
                SemanticJsonArgument({}),
                "--options-json",
                SemanticJsonArgument({}),
            ),
        )
        for index in range(1, unit.user_turn_count + 1)
    )
    return V3GatewayProtocol(steps, tuple(range(1, len(steps) + 1)))


def _synthetic_audio_operation_request(unit: _Unit, *, io_root: Path) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.audio.convert",
            "args": {
                "objects": ["\\Actor-Mixer Hierarchy\\Default Work Unit\\Synthetic"],
                "platforms": ["Windows"],
                "languages": ["SFX"],
            },
            "options": {},
            "io_root": str(io_root),
        },
    }


def _synthetic_gateway_records(
    *,
    options: campaign.CampaignOptions,
    task_root: Path,
    protocol: V3GatewayProtocol,
    version: str,
    invocation_skill_source: Path | None = None,
) -> list[dict[str, Any]]:
    runner = Path(
        os.path.abspath(os.fspath(options.skill_source / "scripts" / "run.py"))
    )
    invocation_runner = Path(
        os.path.abspath(
            os.fspath(
                (invocation_skill_source or options.skill_source)
                / "scripts"
                / "run.py"
            )
        )
    )
    shim = task_root / "broker" / "bin"
    shim.mkdir(parents=True, exist_ok=True)
    (shim / "python").write_text("synthetic broker shim\n", encoding="utf-8")
    replay = CodexGatewayBroker(
        skill_source=options.skill_source,
        invocation_skill_source=invocation_skill_source,
        expected_steps=protocol.steps,
        expected_wwise_version=version,
        runner_environment={},
    )
    transaction_id = "synthetic-transaction"
    transaction_store: TransactionStore | None = None
    awaiting_snapshot = None
    has_draft_preview = any(
        step.subcommand == "preview-from-draft" for step in protocol.steps
    )
    if any(step.subcommand == "transaction-show" for step in protocol.steps) and not has_draft_preview:
        transaction_store = TransactionStore(task_root / "broker" / "state")
        transaction_store.create_preview(
            transaction_id,
            {
                "contract": "waapi-skill.synthetic-campaign-preview/v1",
                "version": version,
            },
        )
        transaction_store.submit_for_confirmation(transaction_id)
        awaiting_snapshot = transaction_store.load_snapshot(transaction_id)
        assert awaiting_snapshot.confirmation_token is not None
    records: list[dict[str, Any]] = []
    draft_store = OperationDraftStore(task_root / "broker" / "state")
    draft_started: dict[str, tuple[str, str, str, int]] = {}
    required_response_values: dict[tuple[str, str], Any] = {}
    for expected_step in protocol.steps:
        for expected_argument in expected_step.arguments:
            if isinstance(expected_argument, DraftTypedActionArgument):
                for binding in expected_argument.response_bindings:
                    key = binding.pointer.removeprefix("/")
                    required_response_values[
                        (binding.step, binding.response_pointer)
                    ] = expected_argument.expected[key]

    def set_pointer(payload: dict[str, Any], pointer: str, value: Any) -> None:
        current: dict[str, Any] = payload
        segments = pointer.removeprefix("/").split("/")
        for segment in segments[:-1]:
            child = current.get(segment)
            if not isinstance(child, dict):
                child = {}
                current[segment] = child
            current = child
        current[segments[-1]] = value

    use_candidate_runner = False
    for index, step in enumerate(protocol.steps, start=1):
        arguments = [*step.gateway_global_arguments, step.subcommand]
        for item in step.arguments:
            if isinstance(item, str):
                arguments.append(item)
            elif isinstance(item, SemanticJsonArgument):
                arguments.append(
                    json.dumps(
                        item.expected,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            elif isinstance(item, DraftTypedActionArgument):
                arguments.extend(typed_action_cli_arguments(item.expected))
            elif isinstance(item, TypedRequestFactsArgument):
                construction = typed_request_construction_for_values(
                    item.contract,
                    args=item.expected_args,
                    options=item.expected_options,
                )
                arguments.extend(
                    _typed_fact_cli_arguments(
                        construction.facts,
                        prefix=item.prefix,
                    )
                )
            elif isinstance(item, InlineTypedOperationArgument):
                arguments.extend(inline_operation_cli_arguments(item.expected)[1:])
            elif isinstance(item, ResponseBinding):
                source = replay._payloads_by_step.get(item.step)  # noqa: SLF001
                if source is None:
                    raise AssertionError("synthetic response binding is unavailable")
                current: Any = source
                for segment in item.pointer.removeprefix("/").split("/"):
                    if isinstance(current, Mapping):
                        current = current.get(segment)
                    elif isinstance(current, list) and segment.isdigit():
                        position = int(segment)
                        current = current[position] if position < len(current) else None
                    else:
                        current = None
                        break
                bound = current
                if not isinstance(bound, (str, int, float, bool)) or bound is None:
                    raise AssertionError("synthetic response binding is unavailable")
                arguments.append(str(bound))
            else:
                raise AssertionError("synthetic protocol argument is unsupported")
        model_argv = [
            str(shim / "python"),
            str(runner if use_candidate_runner else invocation_runner),
            "gateway.py",
            *arguments,
        ]
        resolved = resolve_gateway_invocation(
            model_argv,
            skill_source=options.skill_source,
            invocation_skill_source=invocation_skill_source,
            shim_directory=shim,
        )
        semantic_sha256, execution_arguments = replay._validate_step(  # noqa: SLF001
            step,
            resolved.gateway_arguments,
        )
        structured_refusal = step.allowed_exit_codes == (2,)
        allowed_contracts = gateway_payload_contracts(step.subcommand)
        payload_contract = (
            GATEWAY_RESULT_CONTRACT
            if structured_refusal
            else (
                TYPED_CONTAINER_HANDLE_CONTRACT
                if step.subcommand
                in {"request-map-container", "request-array-item"}
                else next(iter(allowed_contracts))
            )
        )
        payload = {
            "contract": payload_contract,
            "ok": not structured_refusal,
            "command": step.subcommand,
        }
        if structured_refusal:
            payload["error_code"] = step.expected_error_code
        elif step.subcommand == "draft-start":
            operation = str(step.arguments[0])
            schema_digest = operation_request_schema_digest(operation, version)
            composer_digest = operation_composer_digest(operation, version)
            started = draft_store.start(
                operation=operation,
                version=version,
                schema_digest=schema_digest,
                composer_digest=composer_digest,
            )
            draft_started[operation] = (
                started.record.draft_id,
                started.task_authority,
                schema_digest,
                started.record.revision,
            )
            payload.update(
                {
                    "draft": {
                        "draft_id": started.record.draft_id,
                        "revision": started.record.revision,
                        "lifecycle_state": "editable",
                        "binding": {
                            "operation": operation,
                            "version": version,
                            "schema_digest": schema_digest,
                        },
                        **composition_projection(
                            operation,
                            version,
                            started.record.composition,
                        ),
                    },
                    "task_authority": started.task_authority,
                }
            )
        elif step.subcommand == "draft-apply":
            operation = next(reversed(draft_started))
            draft_id, authority, schema_digest, revision = draft_started[operation]
            action_argument = next(
                item
                for item in step.arguments
                if isinstance(item, DraftTypedActionArgument)
            )
            action = dict(action_argument.expected)
            for binding in action_argument.response_bindings:
                action[binding.pointer.removeprefix("/")] = required_response_values[
                    (binding.step, binding.response_pointer)
                ]
            updated = draft_store.apply_action(
                draft_id,
                task_authority=authority,
                expected_revision=revision,
                schema_digest=schema_digest,
                composer_digest=operation_composer_digest(operation, version),
                action=action,
            )
            draft_started[operation] = (
                draft_id,
                authority,
                schema_digest,
                updated.revision,
            )
            payload["draft"] = {
                "draft_id": draft_id,
                "revision": updated.revision,
                "lifecycle_state": "editable",
                "binding": {
                    "operation": operation,
                    "version": version,
                    "schema_digest": schema_digest,
                },
                "action_result": {
                    "created_handles": sorted(
                        value
                        for (source_step, pointer), value in required_response_values.items()
                        if source_step == step.name
                        and pointer.endswith("/created_handles/0")
                    ),
                },
                **composition_projection(
                    operation,
                    version,
                    updated.composition,
                ),
            }
        elif step.subcommand == "draft-check":
            operation = next(reversed(draft_started))
            draft_id, authority, schema_digest, revision = draft_started[operation]
            materialized = draft_store.materialize_request(
                draft_id,
                task_authority=authority,
                expected_revision=revision,
                schema_digest=schema_digest,
                composer_digest=operation_composer_digest(operation, version),
            )
            checked = draft_store.record_check(
                draft_id,
                task_authority=authority,
                expected_revision=revision,
                schema_digest=schema_digest,
                composer_digest=operation_composer_digest(operation, version),
                request_digest=materialized.request_digest,
                project_guard={},
                runtime_guard_fingerprint="b" * 64,
                prepared_digest="c" * 64,
            )
            draft_started[operation] = (
                draft_id,
                authority,
                schema_digest,
                checked.revision,
            )
            payload["draft"] = {
                "draft_id": draft_id,
                "revision": checked.revision,
                "lifecycle_state": "editable",
                "binding": {
                    "operation": operation,
                    "version": version,
                    "schema_digest": schema_digest,
                },
                **composition_projection(
                    operation,
                    version,
                    checked.composition,
                ),
            }
        elif step.subcommand == "draft-inspect":
            operation = next(reversed(draft_started))
            draft_id, _authority, schema_digest, revision = draft_started[operation]
            payload["draft"] = {
                "draft_id": draft_id,
                "revision": revision,
                "lifecycle_state": "editable",
                "binding": {
                    "operation": operation,
                    "version": version,
                    "schema_digest": schema_digest,
                },
            }
        elif step.subcommand in {"request-map-container", "request-array-item"}:
            payload.update(
                {
                    "handle": "trm1-" + "0" * 24,
                    "schema_lineage_token": "synthetic-schema-lineage-token",
                }
            )
        elif step.subcommand == "preview-from-draft":
            operation = next(reversed(draft_started))
            draft_id, authority, schema_digest, revision = draft_started[operation]
            reservation = draft_store.reserve_seal(
                draft_id,
                task_authority=authority,
                expected_revision=revision,
                schema_digest=schema_digest,
                composer_digest=operation_composer_digest(operation, version),
                transaction_id=transaction_id,
                apply=True,
                ttl_seconds=1800,
                policy="ask_before_changes",
            )
            artifact_hash = (
                "a" * 64
            )
            canonical_request = reservation.request
            prepared = {
                "request": canonical_request,
                "cleanup": {"kind": "none"},
            }
            artifact = {
                "request": canonical_request,
                "prepared_operation": prepared,
            }
            transaction_store = TransactionStore(task_root / "broker" / "state")
            transaction_store.create_preview(transaction_id, artifact)
            transaction_store.submit_for_confirmation(transaction_id)
            awaiting_snapshot = transaction_store.load_snapshot(transaction_id)
            artifact_hash = awaiting_snapshot.preview.artifact_hash
            draft_store.commit_seal(
                draft_id,
                task_authority=authority,
                source_revision=reservation.source_revision,
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
                transaction_state="awaiting_confirmation",
            )
            payload.update(
                {
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "awaiting_confirmation",
                    "cleanup": transaction_cleanup_payload(
                        prepared,
                        phase="preview",
                    ),
                }
            )
            payload["agent_result"] = {
                "request": canonical_request,
                "transaction_id": transaction_id,
                "artifact_hash": artifact_hash,
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="preview",
                ),
            }
        elif step.subcommand in {
            "preview",
            "typed-call",
            "typed-operation",
        }:
            payload.update(
                {
                    "transaction_id": transaction_id,
                    "artifact_hash": (
                        awaiting_snapshot.preview.artifact_hash
                        if awaiting_snapshot is not None
                        else "a" * 64
                    ),
                }
            )
        elif step.subcommand == "transaction-show":
            assert awaiting_snapshot is not None
            artifact_hash = awaiting_snapshot.preview.artifact_hash
            event_sequence = awaiting_snapshot.record.event_sequence
            last_event_hash = awaiting_snapshot.record.last_event_hash
            confirmation_token = awaiting_snapshot.confirmation_token
            assert confirmation_token is not None
            gateway_argv = [
                "confirm",
                transaction_id,
                "--confirmation-token",
                confirmation_token,
            ]
            full_argv = [
                "python",
                str(runner.resolve(strict=True)),
                "gateway.py",
                *gateway_argv,
            ]
            next_command: dict[str, Any] = {
                "contract": "waapi-skill.gateway-next-command/v2",
                "command": "confirm",
                "gateway_argv": gateway_argv,
                "full_argv": full_argv,
                "copy_exactly": True,
                "requires_explicit_user_confirmation": True,
            }
            model_command: str | None = None
            if os.name == "nt":
                next_command["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
                shell_command = encode_windows_powershell_argv(full_argv)
                try:
                    model_command = encode_windows_model_argv(full_argv)
                except PlatformCommandError:
                    model_command = None
            else:
                next_command["shell_family"] = "posix-sh"
                shell_command = shlex.join(full_argv)
            if model_command is not None:
                next_command["shell_command"] = shell_command
                next_command["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
            next_command["copy_instruction"] = {
                "contract": "waapi-skill.gateway-command-copy-instruction/v2",
                "source_field": (
                    "model_command"
                    if model_command is not None
                    else "shell_command"
                ),
                "action": "execute_verbatim_as_one_shell_tool_call",
                "forbidden_transformations": [
                    "reconstruct",
                    "shorten",
                    "normalize",
                    "substitute_path_segments",
                    "select_another_field",
                ],
            }
            if model_command is not None:
                next_command["model_command"] = model_command
            else:
                next_command["shell_command"] = shell_command
            payload.update(
                {
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "awaiting_confirmation",
                    "confirmation": {
                        "contract": "waapi-skill.confirmation-binding/v1",
                        "token": confirmation_token,
                        "binding": {
                            "material_contract": "waapi-skill.confirmation-token-material/v1",
                            "transaction_id": transaction_id,
                            "artifact_hash": artifact_hash,
                            "state": "awaiting_confirmation",
                            "event_sequence": event_sequence,
                            "last_event_hash": last_event_hash,
                        },
                    },
                    "next_command": next_command,
                }
            )
        elif step.subcommand == "confirm":
            assert transaction_store is not None
            assert awaiting_snapshot is not None
            confirmed = transaction_store.confirm(
                transaction_id,
                confirmation_token=awaiting_snapshot.confirmation_token,
            )
            payload.update(
                {
                    "transaction_id": transaction_id,
                    "artifact_hash": confirmed.artifact_hash,
                }
            )
        elif step.subcommand == "execute":
            assert transaction_store is not None
            transaction_store.begin_execution(
                transaction_id,
                expected_authorization=TransactionState.CONFIRMED,
            )
            executed = transaction_store.mark_executed_unverified(transaction_id)
            payload.update(
                {
                    "transaction_id": transaction_id,
                    "artifact_hash": executed.artifact_hash,
                    "cleanup": transaction_cleanup_payload(
                        (
                            awaiting_snapshot.preview.artifact["prepared_operation"]
                            if "prepared_operation" in awaiting_snapshot.preview.artifact
                            else {}
                        ),
                        phase="executed",
                        execution_result={},
                    ),
                }
            )
        elif step.subcommand == "verify":
            assert transaction_store is not None
            verification_details = {
                "verification": {
                    "contract": "waapi-skill.synthetic-verification/v1",
                    "operation": (
                        next(reversed(draft_started))
                        if draft_started
                        else "waapi.call"
                    ),
                    "status": "result_schema_checked",
                    "ok": True,
                    "verification_strength": "result_schema_only",
                    "business_state_verified": False,
                    "assertions": [],
                    "readbacks": [],
                }
            }
            verified = transaction_store.record_verification(
                transaction_id,
                TransactionState.RESULT_SCHEMA_CHECKED,
                details=verification_details,
            )
            payload.update(
                {
                    "transaction_id": transaction_id,
                    "artifact_hash": verified.artifact_hash,
                    "verification": verification_details["verification"],
                    "cleanup": transaction_cleanup_payload(
                        (
                            awaiting_snapshot.preview.artifact["prepared_operation"]
                            if "prepared_operation" in awaiting_snapshot.preview.artifact
                            else {}
                        ),
                        phase="verified",
                        execution_result={},
                    ),
                }
            )
        for (source_step, pointer), value in required_response_values.items():
            if source_step == step.name:
                set_pointer(payload, pointer, value)
        if "agent_result" in payload:
            payload["agent_result"] = payload.pop("agent_result")
        runner_command = [
            os.path.abspath(sys.executable),
            str(runner.resolve(strict=True)),
            "gateway.py",
            *execution_arguments,
        ]
        record = {
            "sequence": index,
            "step_name": step.name,
            "authenticated": True,
            "accepted": True,
            "rejection": "",
            "model_argv": model_argv,
            "normalized_model_argv": list(resolved.normalized_model_argv),
            "gateway_arguments": list(resolved.gateway_arguments),
            "raw_argv_sha256": campaign._canonical_sha256(model_argv),
            "argv_sha256": campaign._canonical_sha256(
                list(resolved.normalized_model_argv)
            ),
            "semantic_argv_sha256": semantic_sha256,
            "started_at_unix": float(index),
            "finished_at_unix": float(index) + 0.1,
            "started_at_unix_ns": index * 1_000_000_000,
            "finished_at_unix_ns": index * 1_000_000_000 + 100_000_000,
            "duration_seconds": 0.1,
            "exit_code": 2 if structured_refusal else 0,
            "runner_exit_code": 2 if structured_refusal else 0,
            "payload": payload,
            "payload_sha256": campaign._canonical_sha256(payload),
            "payload_error": "",
            "runner_command_sha256": campaign._canonical_sha256(runner_command),
            "allowed_exit_codes": list(step.allowed_exit_codes),
            "subscription_ack": None,
            "succeeded": True,
        }
        records.append(record)
        replay._payloads_by_step[step.name] = payload  # noqa: SLF001
        use_candidate_runner = _selected_next_command(payload) is not None
    return records


def _synthetic_audio_transaction_request() -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.audio.convert",
            "args": {
                "objects": [r"\Actor-Mixer Hierarchy\ConversionTarget"],
                "platforms": ["Windows"],
                "languages": ["SFX"],
            },
            "options": {},
            "io_root": "/private/synthetic-io",
        },
    }


def _synthetic_soundbank_generate_request() -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [
                {
                    "name": "Main_UI",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                }
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": "/private/synthetic-io",
            "rebuild_soundbanks": False,
            "clear_audio_file_cache": False,
            "rebuild_init_bank": False,
        },
    }


def test_campaign_accepts_soundbank_generate_semantic_protocol_kind() -> None:
    request = _synthetic_soundbank_generate_request()
    protocol = build_transaction_protocol((request,))
    evidence = SimpleNamespace(
        provenance=SimpleNamespace(
            protocol=protocol,
            payload={"version": request["version"]},
        ),
    )
    assert all(
        not isinstance(argument, SemanticJsonArgument)
        for step in protocol.steps
        for argument in step.arguments
    )
    assert campaign._heavy_v3_protocol_operation_request(evidence) == request
    campaign._validate_heavy_v3_completed_transaction_protocol(
        evidence,
        expected_operation_request=request,
    )


def test_campaign_transaction_validator_accepts_only_the_show_token_response_chain() -> None:
    request = _synthetic_audio_transaction_request()
    protocol = build_transaction_protocol((request,))
    evidence = SimpleNamespace(
        provenance=SimpleNamespace(
            protocol=protocol,
            payload={"version": request["version"]},
        ),
    )

    campaign._validate_heavy_v3_completed_transaction_protocol(
        evidence,
        expected_operation_request=request,
    )

    invalid_arguments = (
        (
            3,
            (
                ResponseBinding("tx01.preview", "/transaction_id"),
                "--confirmation-token",
                ResponseBinding(
                    "tx01.transaction-show",
                    "/confirmation/token",
                ),
            ),
        ),
        (
            3,
            (
                ResponseBinding(
                    "tx01.transaction-show",
                    "/transaction_id",
                ),
                "--confirmation-token",
                ResponseBinding(
                    "tx01.transaction-show",
                    "/confirmation/wrong",
                ),
            ),
        ),
        (
            4,
            (ResponseBinding("tx01.transaction-show", "/transaction_id"),),
        ),
        (
            5,
            (ResponseBinding("tx01.confirm", "/transaction_id"),),
        ),
    )
    for index, arguments in invalid_arguments:
        steps = list(protocol.steps)
        steps[index] = replace(steps[index], arguments=arguments)
        tampered = replace(protocol, steps=tuple(steps))
        with pytest.raises(
            campaign.CampaignEvidenceError,
            match="lacks exact preview/confirm/execute/verify binding",
        ):
            campaign._validate_heavy_v3_completed_transaction_protocol(
                SimpleNamespace(
                    provenance=SimpleNamespace(
                        protocol=tampered,
                        payload={"version": request["version"]},
                    ),
                ),
                expected_operation_request=request,
            )


def test_campaign_rejects_transaction_show_with_incomplete_or_misbound_confirmation() -> None:
    step = build_transaction_protocol((_synthetic_audio_transaction_request(),)).steps[2]
    event_sequence = 2
    last_event_hash = "b" * 64
    token = confirmation_token_for(
        transaction_id="synthetic-transaction",
        artifact_hash="a" * 64,
        state="awaiting_confirmation",
        event_sequence=event_sequence,
        last_event_hash=last_event_hash,
    )
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "command": "transaction-show",
        "transaction_id": "synthetic-transaction",
        "artifact_hash": "a" * 64,
        "state": "awaiting_confirmation",
        "confirmation": {
            "contract": "waapi-skill.confirmation-binding/v1",
            "token": token,
            "binding": {
                "material_contract": "waapi-skill.confirmation-token-material/v1",
                "transaction_id": "synthetic-transaction",
                "artifact_hash": "a" * 64,
                "state": "awaiting_confirmation",
                "event_sequence": event_sequence,
                "last_event_hash": last_event_hash,
            },
        },
    }

    campaign._validate_heavy_v3_gateway_payload(
        payload,
        step=step,
        runner_exit_code=0,
    )

    for tampered in (
        {**payload, "confirmation": {"token": token}},
        {
            **payload,
            "confirmation": {
                **payload["confirmation"],
                "binding": {
                    **payload["confirmation"]["binding"],
                    "last_event_hash": "c" * 64,
                },
            },
        },
    ):
        with pytest.raises(
            campaign.CampaignEvidenceError,
            match="confirmation binding is invalid",
        ):
            campaign._validate_heavy_v3_gateway_payload(
                tampered,
                step=step,
                runner_exit_code=0,
            )


def _populate_synthetic_object_query_payload(
    records: Sequence[dict[str, Any]],
    plan: Mapping[str, Any],
) -> None:
    """Mirror the sealed object.get rows in the synthetic broker archive."""

    query_records = [
        record for record in records if record.get("step_name") == "query-object"
    ]
    if len(query_records) != 1:
        raise AssertionError("synthetic object query requires one broker record")
    before = plan["live_binding"]["before_snapshot"]["objects"]
    by_key = {row["key"]: row for row in before}
    rule = plan["delta_rules"][0]
    request = plan["static_expectation"]["request"]["value"]
    primary_keys = (
        rule["bounded_superset_keys"]
        if request["result_strategy"]
        == "bounded_superset_final_answer_filter"
        else rule["exact_expected_keys"]
    )

    primary_stream = list(primary_keys)
    if rule["primary_row_policy"] == "parent_projection_per_source_row":
        primary_stream = [
            key
            for key in primary_keys
            for _ in range(
                sum(
                    row["type"] == "Sound"
                    and row["parent_id"] == by_key[key]["id"]
                    for row in before
                )
            )
        ][: request["take"]]
    elif rule["primary_row_policy"] not in {
        "unique_identity_rows",
        "ancestor_identity_rows",
    }:
        raise AssertionError("synthetic object query uses an unknown primary policy")

    rows: list[dict[str, Any]] = []
    for key in primary_stream:
        item = by_key[key]
        properties = {
            value["name"]: value["value"] for value in item["properties"]
        }
        references = {
            value["name"]: value["target_id"] for value in item["references"]
        }
        row: dict[str, Any] = {
            "id": item["id"],
            "name": item["name"],
            "type": item["type"],
            "path": item["path"],
            "parent": (
                {"id": item["parent_id"]}
                if item["parent_id"] is not None
                else None
            ),
            "notes": item["notes"],
        }
        if "childrenCount" in request["return_fields"]:
            row["childrenCount"] = item["children_count"]
        for property_name, property_value in properties.items():
            row[f"@{property_name}"] = property_value
        for reference_name, reference_id in references.items():
            row[reference_name] = {"id": reference_id}
        if item["source_language"] is not None:
            row["audioSource:language"] = {"name": item["source_language"]}
        if item["is_included"] is not None:
            row["isIncluded"] = item["is_included"]
        rows.append(row)

    if rule["derived_row_policy"] == "active_audio_sources_for_sound_rows":
        rows.extend(
            {
                "id": item["active_source_id"],
                "name": item["active_source_name"],
                "type": "AudioFileSource",
                "path": item["active_source_path"],
                "parent": {"id": item["id"]},
                "audioSource:language": {"name": item["source_language"]},
            }
            for key in rule["bounded_superset_keys"]
            if (item := by_key[key])["type"] == "Sound"
            and item["source_language"] is not None
        )
    elif rule["derived_row_policy"] != "none":
        raise AssertionError("synthetic object query uses an unknown derived policy")

    record = query_records[0]
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "command": "query-object",
        "query_bound": {"mode": "take", "value": request["take"]},
        "count": len(rows),
        "objects": rows,
    }
    record["payload"] = payload
    record["payload_sha256"] = campaign._canonical_sha256(payload)


def _synthetic_events(
    *,
    thread_id: str,
    records: Sequence[Mapping[str, Any]],
    final_response: str,
    read_paths: Sequence[Path] = (),
    windows_skill_read_source: Path | None = None,
    platform_name: str | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> str:
    events: list[dict[str, Any]] = [
        {"type": "thread.started", "thread_id": thread_id},
        {"type": "turn.started"},
    ]
    for index, path in enumerate(read_paths, start=1):
        item_id = f"read-{index}"
        relative_skill_path: Path | None = None
        if (
            windows_powershell_core_host is not None
            and windows_skill_read_source is not None
        ):
            try:
                relative_skill_path = path.relative_to(windows_skill_read_source)
            except ValueError:
                pass
        if relative_skill_path is not None:
            path_text = str(
                PureWindowsPath(".agents")
                / "skills"
                / "waapi-skill"
                / PureWindowsPath(*relative_skill_path.parts)
            )
            script = (
                "Get-Content -Raw -Encoding UTF8 '"
                + path_text.replace("'", "''")
                + "'"
            )
            command = _synthetic_shell_tool_command(
                script,
                platform_name="nt",
                windows_powershell_core_host=windows_powershell_core_host,
            )
        else:
            command = _synthetic_command(
                ("cat", os.path.abspath(os.fspath(path))),
                platform_name=platform_name,
                windows_powershell_core_host=windows_powershell_core_host,
            )
        events.extend(
            (
                {
                    "type": "item.started",
                    "item": {"id": item_id, "type": "command_execution"},
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": item_id,
                        "type": "command_execution",
                        "command": command,
                        "exit_code": 0,
                        "status": "completed",
                        "aggregated_output": path.read_text(encoding="utf-8"),
                    },
                },
            )
        )
    selected_continuation: str | None = None
    for index, record in enumerate(records, start=1):
        item_id = f"gateway-{index}"
        if selected_continuation is None:
            command = _synthetic_command(
                tuple(str(value) for value in record["model_argv"]),
                platform_name=platform_name,
                windows_powershell_core_host=windows_powershell_core_host,
            )
        else:
            command = _synthetic_shell_tool_command(
                selected_continuation,
                platform_name=platform_name,
                windows_powershell_core_host=windows_powershell_core_host,
            )
        events.extend(
            (
                {
                    "type": "item.started",
                    "item": {"id": item_id, "type": "command_execution"},
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": item_id,
                        "type": "command_execution",
                        "command": command,
                        "exit_code": record["exit_code"],
                        "status": (
                            "completed" if record["exit_code"] == 0 else "failed"
                        ),
                        "aggregated_output": json.dumps(
                            record["payload"], ensure_ascii=False
                        ),
                    },
                },
            )
        )
        selected_continuation = _selected_next_command(record["payload"])
    events.extend(
        (
            {
                "type": "item.completed",
                "item": {
                    "id": "agent-message",
                    "type": "agent_message",
                    "text": final_response,
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
        )
    )
    return "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
        for item in events
    )


def _selected_next_command(payload: Mapping[str, Any]) -> str | None:
    """Select only the response field named by its closed copy instruction."""

    next_command = payload.get("next_command")
    if next_command is None:
        return None
    if not isinstance(next_command, Mapping):
        raise AssertionError("synthetic next_command must be an object")
    copy_instruction = next_command.get("copy_instruction")
    if not isinstance(copy_instruction, Mapping):
        raise AssertionError("synthetic next_command lacks its copy instruction")
    source_field = copy_instruction.get("source_field")
    if source_field not in {"model_command", "shell_command"}:
        raise AssertionError("synthetic next_command source field is unsupported")
    if "model_command" in next_command and source_field != "model_command":
        raise AssertionError(
            "synthetic Windows continuation must not select shell_command when "
            "model_command exists"
        )
    command = next_command.get(source_field)
    if not isinstance(command, str) or not command:
        raise AssertionError("synthetic next_command selected source is unavailable")
    return command


def _synthetic_shell_tool_command(
    command: str,
    *,
    platform_name: str | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> str:
    """Render a Gateway-selected command as one synthetic Codex shell call."""

    effective_platform = os.name if platform_name is None else platform_name
    if effective_platform == "nt":
        if windows_powershell_core_host is None:
            raise AssertionError(
                "synthetic Windows commands require one attested PowerShell Core host"
            )
        return shlex.join(
            (
                windows_powershell_core_host.executable,
                "-NoProfile",
                "-Command",
                command,
            )
        )
    if effective_platform == "posix":
        return command
    raise AssertionError(f"unsupported synthetic command platform: {effective_platform}")


def _synthetic_command(
    argv: Sequence[str],
    *,
    platform_name: str | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> str:
    """Encode synthetic Codex JSONL with its host-independent shlex grammar."""

    effective_platform = os.name if platform_name is None else platform_name
    if effective_platform == "nt":
        if windows_powershell_core_host is None:
            raise AssertionError(
                "synthetic Windows commands require one attested PowerShell Core host"
            )
        encoded_continuation = encode_windows_powershell_argv(argv)
        return shlex.join(
            (
                windows_powershell_core_host.executable,
                "-NoProfile",
                "-Command",
                encoded_continuation,
            )
        )
    if effective_platform == "posix":
        return shlex.join(argv)
    raise AssertionError(f"unsupported synthetic command platform: {effective_platform}")


def test_synthetic_command_uses_exact_host_command_grammar() -> None:
    argv = (
        r"C:\Program Files\Python\python.exe",
        r"C:\Skill Path\run.py",
        "--request-json",
        '{"name":"雷雨 & wind"}',
    )

    host = WindowsPowerShellCoreHost(
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        version="7.6.4",
        native_argument_passing="Windows",
        sha256="a" * 64,
    )
    rendered = _synthetic_command(
        argv, platform_name="nt", windows_powershell_core_host=host
    )
    outer = tuple(shlex.split(rendered, posix=True))
    assert rendered == shlex.join(
        (host.executable, "-NoProfile", "-Command", outer[3])
    )
    assert outer[:3] == (host.executable, "-NoProfile", "-Command")
    assert decode_windows_powershell_argv(outer[3]) == argv
    assert tuple(shlex.split(_synthetic_command(argv, platform_name="posix"))) == argv


def test_synthetic_windows_reads_use_relative_get_content_only_for_skill(
    tmp_path: Path,
) -> None:
    host = WindowsPowerShellCoreHost(
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        version="7.6.4",
        native_argument_passing="Windows",
        sha256="a" * 64,
    )
    skill_install = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill_read = skill_install / "SKILL.md"
    skill_read.parent.mkdir(parents=True)
    skill_read.write_text("# skill\n", encoding="utf-8")
    prompt_asset = tmp_path / "scenario" / "owned" / "inputs" / "import.tsv"
    prompt_asset.parent.mkdir(parents=True)
    prompt_asset.write_text("Object Path\n<Sound>City_A\n", encoding="utf-8")

    rows = [
        json.loads(line)
        for line in _synthetic_events(
            thread_id="thread-windows-read-shapes",
            records=(),
            final_response="done",
            read_paths=(skill_read, prompt_asset),
            windows_skill_read_source=skill_install,
            platform_name="nt",
            windows_powershell_core_host=host,
        ).splitlines()
    ]
    commands = [
        row["item"]["command"]
        for row in rows
        if row.get("type") == "item.completed"
        and isinstance(row.get("item"), Mapping)
        and row["item"].get("type") == "command_execution"
    ]
    skill_outer = tuple(shlex.split(commands[0], posix=True))
    asset_outer = tuple(shlex.split(commands[1], posix=True))

    assert skill_outer[:3] == (host.executable, "-NoProfile", "-Command")
    assert skill_outer[3] == (
        r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'"
    )
    assert asset_outer[:3] == (host.executable, "-NoProfile", "-Command")
    assert decode_windows_powershell_argv(asset_outer[3]) == (
        "cat",
        os.path.abspath(os.fspath(prompt_asset)),
    )


def test_synthetic_response_binding_selects_model_command_not_legacy_fallback() -> None:
    payload = {
        "next_command": {
            "contract": "waapi-skill.gateway-next-command/v2",
            "shell_command": "powershell.exe -EncodedCommand legacy",
            "copy_instruction": {
                "contract": "waapi-skill.gateway-command-copy-instruction/v2",
                "source_field": "model_command",
            },
            "model_command": "python 'run.py' 'gateway.py' 'confirm' 'tx1'",
        }
    }

    assert _selected_next_command(payload) == payload["next_command"][
        "model_command"
    ]

    tampered = copy.deepcopy(payload)
    tampered["next_command"]["copy_instruction"]["source_field"] = "shell_command"
    with pytest.raises(
        AssertionError,
        match="must not select shell_command",
    ):
        _selected_next_command(tampered)


def _soundbank_refusal_broker_fixture(
    tmp_path: Path,
) -> tuple[
    campaign.CampaignOptions,
    Path,
    V3GatewayProtocol,
    list[dict[str, Any]],
    tuple[Any, ...],
]:
    options = _options(tmp_path)
    unit = _soundbank_unit(
        "O22-SB-PROCESS-DEF-05",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        primary_count=0,
    )
    scenario_root = tmp_path / "scenario"
    (scenario_root / "owned").mkdir(parents=True)
    protocol, _sections = _synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    task_root = tmp_path / "task"
    task_root.mkdir()
    records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version=unit.version,
    )
    events = parse_jsonl_events(
        _synthetic_events(
            thread_id="thread-refusal",
            records=records,
            final_response="该输入按封装边界被拒绝。",
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
    )
    return (
        options,
        task_root,
        protocol,
        records,
        completed_command_records(
            events,
            windows_powershell_core_host=options.windows_powershell_core_host,
        ),
    )


def test_campaign_broker_seal_accepts_expected_exit2_failed_command_status(
    tmp_path: Path,
) -> None:
    options, task_root, protocol, records, command_records = (
        _soundbank_refusal_broker_fixture(tmp_path)
    )

    assert len(command_records) == len(protocol.steps)
    assert [(record.exit_code, record.status) for record in command_records] == [
        (0, "completed"),
        (2, "failed"),
    ]
    campaign._validate_heavy_v3_broker_records(
        records,
        task_root=task_root,
        steps=protocol.steps,
        command_records=[
            campaign._json_canonical_value(asdict(record))
            for record in command_records
        ],
        options=options,
        version="2022.1",
        label="expected structured refusal",
    )


def test_campaign_broker_replay_accepts_exact_task_install_and_candidate(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    task_root = tmp_path / "task"
    workspace = task_root / "agent-workspace"
    installed = workspace_skill_install_path(workspace)
    installed.parent.mkdir(parents=True)
    installed.write_text("sealed install attestation\n", encoding="utf-8")
    unit = _unit(1)
    protocol = _synthetic_protocol(
        unit,
        scenario_root=tmp_path / "scenario",
        visible_values={},
    )
    installed_records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version=unit.version,
        invocation_skill_source=installed,
    )
    canonical_records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version=unit.version,
    )

    def archived_commands(records: Sequence[Mapping[str, Any]]) -> list[Any]:
        events = parse_jsonl_events(
            _synthetic_events(
                thread_id="thread-runner-replay",
                records=records,
                final_response="done",
                windows_powershell_core_host=options.windows_powershell_core_host,
            )
        )
        return [
            campaign._json_canonical_value(asdict(record))
            for record in completed_command_records(
                events,
                windows_powershell_core_host=options.windows_powershell_core_host,
            )
        ]

    installed_commands = archived_commands(installed_records)
    campaign._validate_heavy_v3_broker_records(
        installed_records,
        task_root=task_root,
        steps=protocol.steps,
        command_records=installed_commands,
        options=options,
        version=unit.version,
        label="installed runner replay",
    )

    canonical_commands = archived_commands(canonical_records)
    campaign._validate_heavy_v3_broker_records(
        canonical_records,
        task_root=task_root,
        steps=protocol.steps,
        command_records=canonical_commands,
        options=options,
        version=unit.version,
        label="canonical runner replay",
    )

    third_root = tmp_path / "third-skill"
    third_records = copy.deepcopy(canonical_records)
    third_commands = copy.deepcopy(canonical_commands)
    third_runner = str(third_root / "scripts" / "run.py")
    third_records[0]["model_argv"][1] = third_runner
    third_commands[0]["argv"][1] = third_runner
    with pytest.raises(
        CampaignEvidenceError,
        match="broker argv cannot replay protocol step",
    ):
        campaign._validate_heavy_v3_broker_records(
            third_records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=third_commands,
            options=options,
            version=unit.version,
            label="third runner replay",
        )


def test_campaign_broker_seal_binds_confirmation_to_archived_transaction_store(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    task_root = tmp_path / "task"
    task_root.mkdir()
    protocol = build_transaction_protocol((_synthetic_audio_transaction_request(),))
    records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version="2025.1",
    )
    command_records = completed_command_records(
        parse_jsonl_events(
            _synthetic_events(
                thread_id="thread-confirmation-store",
                records=records,
                final_response="已完成确认事务。",
                windows_powershell_core_host=options.windows_powershell_core_host,
            )
        ),
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    serialized_commands = [
        campaign._json_canonical_value(asdict(record))
        for record in command_records
    ]

    campaign._validate_heavy_v3_broker_records(
        records,
        task_root=task_root,
        steps=protocol.steps,
        command_records=serialized_commands,
        options=options,
        version="2025.1",
        label="durable confirmation",
    )

    events_path = (
        task_root
        / "broker"
        / "state"
        / "transactions"
        / "synthetic-transaction"
        / "events.jsonl"
    )
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    events[1]["event_hash"] = "f" * 64
    matrix.write_text(
        events_path,
        "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            for event in events
        ),
    )

    with pytest.raises(
        CampaignEvidenceError,
        match="archived durable transaction",
    ):
        campaign._validate_heavy_v3_broker_records(
            records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=serialized_commands,
            options=options,
            version="2025.1",
            label="tampered durable confirmation",
        )


def test_campaign_archive_rejects_equivalent_requoted_continuation(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    task_root = tmp_path / "task"
    task_root.mkdir()
    protocol = build_transaction_protocol((_synthetic_audio_transaction_request(),))
    records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version="2025.1",
    )
    command_records = list(
        completed_command_records(
            parse_jsonl_events(
                _synthetic_events(
                    thread_id="thread-continuation-binding",
                    records=records,
                    final_response="已完成确认事务。",
                    windows_powershell_core_host=(
                        options.windows_powershell_core_host
                    ),
                )
            ),
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
    )
    prior_index = next(
        index
        for index, record in enumerate(records[:-1])
        if _selected_next_command(record["payload"]) is not None
    )
    selected = _selected_next_command(records[prior_index]["payload"])
    assert selected is not None
    if options.windows_powershell_core_host is not None:
        equivalent = selected.replace("'gateway.py'", "gateway.py", 1)
        tampered_command = _synthetic_shell_tool_command(
            equivalent,
            platform_name="nt",
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
    else:
        equivalent = selected.replace(" gateway.py ", " 'gateway.py' ", 1)
        tampered_command = _synthetic_shell_tool_command(
            equivalent,
            platform_name="posix",
        )
    assert equivalent != selected
    continuation_index = prior_index + 1
    assert tuple(shlex.split(equivalent)) == command_records[continuation_index].argv
    command_records[continuation_index] = replace(
        command_records[continuation_index],
        command=tampered_command,
    )

    with pytest.raises(
        CampaignEvidenceError,
        match="response-derived Gateway continuation binding is invalid",
    ):
        campaign._validate_heavy_v3_broker_records(
            records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=[
                campaign._json_canonical_value(asdict(record))
                for record in command_records
            ],
            options=options,
            version="2025.1",
            label="requoted continuation",
        )


@pytest.mark.parametrize(
    ("exit_code", "status"),
    (
        (2, "completed"),
        (2, "in_progress"),
        (2, ""),
        (0, "failed"),
        (None, "failed"),
    ),
    ids=(
        "nonzero-marked-completed",
        "unfinished",
        "missing-status",
        "exit-mismatch",
        "missing-exit",
    ),
)
def test_campaign_broker_seal_rejects_incomplete_or_inconsistent_codex_status(
    tmp_path: Path,
    exit_code: int | None,
    status: str,
) -> None:
    options, task_root, protocol, records, command_records = (
        _soundbank_refusal_broker_fixture(tmp_path)
    )
    tampered = [
        *command_records[:-1],
        replace(command_records[-1], exit_code=exit_code, status=status),
    ]

    with pytest.raises(
        CampaignEvidenceError,
        match="not uniquely aligned to Codex facts",
    ):
        campaign._validate_heavy_v3_broker_records(
            records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=[
                campaign._json_canonical_value(asdict(record))
                for record in tampered
            ],
            options=options,
            version="2022.1",
            label="tampered structured refusal",
        )


def test_campaign_broker_seal_rejects_unreviewed_nonzero_exit(
    tmp_path: Path,
) -> None:
    options, task_root, protocol, records, command_records = (
        _soundbank_refusal_broker_fixture(tmp_path)
    )
    records[-1]["exit_code"] = 1
    records[-1]["runner_exit_code"] = 1
    abnormal = [
        *command_records[:-1],
        replace(command_records[-1], exit_code=1, status="failed"),
    ]

    with pytest.raises(
        CampaignEvidenceError,
        match="hashes, exits, or timing are inconsistent",
    ):
        campaign._validate_heavy_v3_broker_records(
            records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=[
                campaign._json_canonical_value(asdict(record))
                for record in abnormal
            ],
            options=options,
            version="2022.1",
            label="unreviewed runtime failure",
        )


def _synthetic_required_reference(unit: _Unit) -> str:
    if (
        unit.scenario.api in {
            "ak.wwise.core.object.get",
            "ak.wwise.core.mediaPool.get",
        }
        or unit.scenario.item_type == "topic"
    ):
        return "references/waapi-query.md"
    return "references/waapi-operate.md"


def _synthetic_first_turn_reads(
    options: campaign.CampaignOptions,
    unit: _Unit,
    *,
    skill_source: Path | None = None,
) -> tuple[Path, Path]:
    source = skill_source or options.skill_source
    return (
        source / "SKILL.md",
        source / _synthetic_required_reference(unit),
    )


def _synthetic_runtime_skill_read_source(
    options: campaign.CampaignOptions,
    skill_install: Path,
) -> Path:
    return (
        skill_install
        if options.windows_powershell_core_host is not None
        else options.skill_source
    )


def _synthetic_codex_facts(
    *,
    options: campaign.CampaignOptions,
    task_root: Path,
    turn_root: Path,
    turn_index: int,
    prompt: str,
    thread_id: str,
    events_text: str,
    protocol: V3GatewayProtocol,
    version: str,
    exit_status: int = 0,
) -> dict[str, Any]:
    events = parse_jsonl_events(events_text)
    invalid = count_invalid_jsonl_lines(events_text)
    session = audit_session_events(events, invalid_json_line_count=invalid)
    command_records = completed_command_records(
        events,
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    command_facts = classify_task_commands(
        command_records,
        workspace=task_root / "agent-workspace",
        skill_source=options.skill_source,
        expected_gateway_subcommands=tuple(step.subcommand for step in protocol.steps),
        expected_wwise_version=version,
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
    )
    command = (
        build_task_exec_command(config, prompt=prompt, writable_dir=turn_root)
        if turn_index == 1
        else build_task_resume_command(
            config,
            thread_id=thread_id,
            prompt=prompt,
            writable_dir=turn_root,
        )
    )
    session_payload = asdict(session)
    session_payload["passed"] = session.passed
    return {
        "command": command,
        "exit_status": exit_status,
        "duration_seconds": 0.25,
        "timed_out": False,
        "thread_id": session.thread_ids[0] if len(session.thread_ids) == 1 else "",
        "final_response": final_agent_message(events),
        "usage": turn_usage(events),
        "event_count": len(events),
        "collab_call_count": session.collab_call_count,
        "file_change_count": session.file_change_count,
        "prompt_audit": {
            "passed": True,
            "has_memory": False,
            "prompt_sha256": hashlib.sha256(
                f"synthetic prompt audit {turn_index}".encode("utf-8")
            ).hexdigest(),
        },
        "isolation_audit": {"passed": True},
        "session_audit": session_payload,
        "command_facts": asdict(command_facts),
        "created_files": [],
        "modified_files": [],
        "deleted_files": [],
        "created_source_files": [],
        "modified_source_files": [],
        "deleted_source_files": [],
        "skill_tree_sha256_before": "b" * 64,
        "skill_tree_sha256_after": "b" * 64,
        "skill_tree_unchanged": True,
    }


def _synthetic_materialized_object(*, key: str = "synthetic") -> dict[str, Any]:
    return {
        "key": key,
        "id": "{11111111-1111-1111-1111-111111111111}",
        "name": "SyntheticObject",
        "type": "ActorMixer",
        "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\SyntheticObject",
        "parent_id": "{22222222-2222-2222-2222-222222222222}",
        "notes": "synthetic",
        "properties": [{"name": "Volume", "value": -3.0}],
        "references": [],
        "source_language": None,
        "is_included": True,
        "children_count": 0,
        "active_source_id": None,
        "active_source_name": None,
        "active_source_path": None,
    }


def _synthetic_object_snapshot(objects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "objects": [dict(item) for item in objects],
        "absent_paths": [],
        "sibling_prefix_rows": [],
    }
    return {**payload, "digest": campaign._canonical_sha256(payload)}


def _synthetic_object_oracle(
    *,
    unit: _Unit,
    final_response: str,
    business_oracle_plan: BusinessOraclePlanEvidence,
) -> dict[str, Any]:
    plan = business_oracle_plan.payload
    before = plan["live_binding"]["before_snapshot"]
    if unit.scenario.api == "ak.wwise.core.object.get":
        rule = plan["delta_rules"][0]
        request = plan["static_expectation"]["request"]["value"]
        expected_payload = (
            rule["bounded_superset_keys"]
            if request.get("result_strategy")
            == "bounded_superset_final_answer_filter"
            else rule["exact_expected_keys"]
        )
        by_key = {row["key"]: row for row in before["objects"]}
        derived_rows = _synthetic_object_derived_rows(
            rule,
            by_key,
        )
        observed_primary = _synthetic_object_primary_stream(
            rule,
            request,
            before["objects"],
        )
        (
            required_tokens,
            excluded_tokens,
            paired_rows,
            deduplicated_parent_rows,
            coverage_summary,
            answer_order,
        ) = _synthetic_object_answer_proof(
            rule,
            by_key,
            final_response,
        )
        verification = {
            "phase": "query",
            "passed": True,
            "failures": [],
            "evidence": {
                "before": before,
                "after": before,
                "observed_keys": observed_primary,
                "expected_payload_keys": list(expected_payload),
                "primary_row_policy": rule["primary_row_policy"],
                "raw_row_count": len(observed_primary) + len(derived_rows),
                "query_bound": {"mode": "take", "value": request["take"]},
                "bound_reached": (
                    len(observed_primary) + len(derived_rows) == request["take"]
                ),
                "derived_row_policy": rule["derived_row_policy"],
                "derived_rows": derived_rows,
                "required_keys": list(rule["exact_expected_keys"]),
                "excluded_keys": list(rule["excluded_keys"]),
                "final_answer_policy": rule["final_answer_policy"],
                "required_identity_tokens": required_tokens,
                "excluded_identity_tokens": excluded_tokens,
                "paired_rows": paired_rows,
                "deduplicated_parent_rows": deduplicated_parent_rows,
                "coverage_summary": coverage_summary,
                "observed_answer_order": answer_order,
                "final_response_sha256": hashlib.sha256(
                    final_response.encode("utf-8")
                ).hexdigest(),
            },
        }
    else:
        verification = _synthetic_object_mutation_verification(plan)
    return {
        "contract": campaign.HEAVY_V3_ORACLE_CONTRACT,
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "api": unit.scenario.api,
        "runner": "project",
        "business_oracle_plan_sha256": business_oracle_plan.sha256,
        "verification": verification,
    }


def _synthetic_object_final_response(plan: Mapping[str, Any]) -> str:
    rule = plan["delta_rules"][0]
    by_key = {
        row["key"]: row
        for row in plan["live_binding"]["before_snapshot"]["objects"]
    }
    if rule["final_answer_policy"] == "name_and_id":
        identity_text = " ".join(
            f"{by_key[key]['name']} {by_key[key]['id']}"
            for key in rule["exact_expected_keys"]
        )
        return f"waapi-skill 已加载。{identity_text}。"
    if rule["final_answer_policy"] == "deduplicated_parent_summary":
        by_id = {row["id"]: row for row in by_key.values()}
        rows = []
        for key in rule["expected_order_keys"]:
            parent = by_key[key]
            bus_id = next(
                item["target_id"]
                for item in parent["references"]
                if item["name"] == "OutputBus"
            )
            bus = by_id[bus_id]
            rows.append(
                f"| {parent['name']} | {parent['id']} | `{parent['path']}` | "
                f"{parent['children_count']} | {parent['notes']} | {bus['name']} |"
            )
        return "\n".join(
            (
                "waapi-skill 已加载。",
                "| 名称 | GUID | 路径 | 直接子对象数 | 备注 | Output Bus |",
                "|---|---|---|---:|---|---|",
                *rows,
                "汇总：命中 3 个父容器，确认覆盖 10 个直接子 Sound；10 条上限已触及，结果可能不完整。",
            )
        )
    if rule["final_answer_policy"] == "ordered_ancestor_summary":
        rows = []
        for ordinal, key in enumerate(rule["expected_order_keys"], start=1):
            ancestor = by_key[key]
            rows.append(
                f"| {ordinal} | {ancestor['name']} | {ancestor['id']} | {ancestor['type']} | "
                f"`{ancestor['path']}` | {ancestor['children_count']} | "
                f"{ancestor['notes'] or '无'} |"
            )
        return "\n".join(
            (
                "waapi-skill 已加载。",
                "| 层级 | 名称 | GUID | 类型 | 完整路径 | childrenCount | 备注 |",
                "|---:|---|---|---|---|---:|---|",
                *rows,
                "类型汇总：恰好 1 个 Random Container、2 个 Actor Mixer、2 个 Work Unit。",
                "并且经过 Default Work Unit。",
            )
        )
    assert rule["final_answer_policy"] == "paired_path_rows"
    id_to_key = {row["id"]: key for key, row in by_key.items()}
    rows = []
    for child_key in rule["expected_order_keys"]:
        child = by_key[child_key]
        parent_key = id_to_key.get(child["parent_id"])
        if child["type"] != "Sound" or parent_key not in rule["exact_expected_keys"]:
            continue
        parent = by_key[parent_key]
        volume = next(
            item["value"] for item in child["properties"] if item["name"] == "Volume"
        )
        rows.append(
            f"| `{parent['path']}` | `{child['path']}` | {child['source_language']} | "
            f"{float(volume):.1f} dB | {child['notes']} |"
        )
    return "\n".join(
        (
            "waapi-skill 已加载。",
            "| Parent | Sound | Language | Volume | Notes |",
            "|---|---|---|---:|---|",
            *rows,
        )
    )


def _synthetic_object_derived_rows(
    rule: Mapping[str, Any],
    by_key: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if rule["derived_row_policy"] == "none":
        return []
    assert rule["derived_row_policy"] == "active_audio_sources_for_sound_rows"
    return [
        {
            "sound_key": key,
            "sound_id": by_key[key]["id"],
            "id": by_key[key]["active_source_id"],
            "name": by_key[key]["active_source_name"],
            "type": "AudioFileSource",
            "path": by_key[key]["active_source_path"],
            "parent_id": by_key[key]["id"],
            "language": by_key[key]["source_language"],
        }
        for key in rule["bounded_superset_keys"]
        if by_key[key]["type"] == "Sound"
        and by_key[key]["source_language"] is not None
    ]


def _synthetic_object_primary_stream(
    rule: Mapping[str, Any],
    request: Mapping[str, Any],
    before_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    expected = (
        rule["bounded_superset_keys"]
        if request["result_strategy"] == "bounded_superset_final_answer_filter"
        else rule["exact_expected_keys"]
    )
    if rule["primary_row_policy"] in {
        "unique_identity_rows",
        "ancestor_identity_rows",
    }:
        return list(expected)
    assert rule["primary_row_policy"] == "parent_projection_per_source_row"
    by_key = {row["key"]: row for row in before_rows}
    return [
        key
        for key in expected
        for _ in range(
            sum(
                row["type"] == "Sound"
                and row["parent_id"] == by_key[key]["id"]
                for row in before_rows
            )
        )
    ][: request["take"]]


def _synthetic_object_answer_proof(
    rule: Mapping[str, Any],
    by_key: Mapping[str, Mapping[str, Any]],
    final_response: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[str],
]:
    if rule["final_answer_policy"] == "name_and_id":
        folded = final_response.casefold()
        return (
            [
                {
                    "key": key,
                    "name": by_key[key]["name"],
                    "id": by_key[key]["id"],
                    "name_present": by_key[key]["name"].casefold() in folded,
                    "id_present": by_key[key]["id"].casefold() in folded,
                }
                for key in rule["exact_expected_keys"]
            ],
            [
                {
                    "key": key,
                    "id": by_key[key]["id"],
                    "id_present": by_key[key]["id"].casefold() in folded,
                }
                for key in rule["excluded_keys"]
            ],
            [],
            [],
            None,
            [],
        )
    if rule["final_answer_policy"] == "deduplicated_parent_summary":
        lines = final_response.splitlines()
        folded = final_response.casefold()
        by_id = {row["id"]: row for row in by_key.values()}
        required = [
            {
                "key": key,
                "name": by_key[key]["name"],
                "id": by_key[key]["id"],
                "name_present": by_key[key]["name"].casefold() in folded,
                "id_present": by_key[key]["id"].casefold() in folded,
            }
            for key in rule["exact_expected_keys"]
        ]
        excluded = [
            {
                "key": key,
                "id": by_key[key]["id"],
                "id_present": by_key[key]["id"].casefold() in folded,
            }
            for key in rule["excluded_keys"]
        ]
        parents = []
        order = []
        for ordinal, key in enumerate(rule["expected_order_keys"], start=1):
            parent = by_key[key]
            matches = [
                (index, offset)
                for index, line in enumerate(lines)
                for offset in campaign._campaign_path_token_offsets(
                    line, parent["path"]
                )
            ]
            assert len(matches) == 1
            line_index = matches[0][0]
            line = lines[line_index]
            bus_id = next(
                item["target_id"]
                for item in parent["references"]
                if item["name"] == "OutputBus"
            )
            bus = by_id[bus_id]
            parents.append(
                {
                    "key": key,
                    "name": parent["name"],
                    "id": parent["id"],
                    "path": parent["path"],
                    "children_count": parent["children_count"],
                    "notes": parent["notes"],
                    "output_bus_id": bus["id"],
                    "output_bus_name": bus["name"],
                    "line_index": line_index,
                    "line_sha256": hashlib.sha256(
                        line.encode("utf-8")
                    ).hexdigest(),
                }
            )
            order.append(key)
        summary_index = next(
            index
            for index, line in enumerate(lines)
            if "3" in line and "10" in line and "Sound" in line
        )
        coverage = {
            "unique_parent_count": 3,
            "confirmed_sound_count": 10,
            "direct_child_object_count": sum(
                by_key[key]["children_count"] for key in rule["exact_expected_keys"]
            ),
            "summary_line_index": summary_index,
            "bound_disclosed": True,
            "incomplete_disclosed": True,
            "claims_twelve_sounds": False,
        }
        return required, excluded, [], parents, coverage, order
    if rule["final_answer_policy"] == "ordered_ancestor_summary":
        lines = final_response.splitlines()
        folded = final_response.casefold()
        required = [
            {
                "key": key,
                "name": by_key[key]["name"],
                "id": by_key[key]["id"],
                "name_present": by_key[key]["name"].casefold() in folded,
                "id_present": by_key[key]["id"].casefold() in folded,
            }
            for key in rule["exact_expected_keys"]
        ]
        excluded = [
            {
                "key": key,
                "id": by_key[key]["id"],
                "id_present": by_key[key]["id"].casefold() in folded,
            }
            for key in rule["excluded_keys"]
        ]
        ancestors: list[dict[str, Any]] = []
        order: list[str] = []
        row_line_indexes: set[int] = set()
        for ordinal, key in enumerate(rule["expected_order_keys"], start=1):
            ancestor = by_key[key]
            matches = [
                (index, offset)
                for index, line in enumerate(lines)
                for offset in campaign._campaign_path_token_offsets(
                    line, ancestor["path"]
                )
            ]
            assert len(matches) == 1
            line_index = matches[0][0]
            line = lines[line_index]
            row_line_indexes.add(line_index)
            ancestors.append(
                {
                    "key": key,
                    "name": ancestor["name"],
                    "id": ancestor["id"],
                    "type": ancestor["type"],
                    "path": ancestor["path"],
                    "children_count": ancestor["children_count"],
                    "notes": ancestor["notes"],
                    "notes_present": campaign._campaign_ancestor_notes_present(
                        line, ancestor["notes"]
                    ),
                    "ordinal": ordinal,
                    "ordinal_present": True,
                    "numeric_values": [
                        float(ordinal),
                        float(ancestor["children_count"]),
                    ],
                    "line_index": line_index,
                    "line_sha256": hashlib.sha256(
                        line.encode("utf-8")
                    ).hexdigest(),
                }
            )
            order.append(key)
        summary_lines: set[int] = set()
        for label, count in (
            ("RandomSequenceContainer", 1),
            ("ActorMixer", 2),
            ("WorkUnit", 2),
        ):
            summary_lines.update(
                campaign._campaign_exact_summary_count_lines(
                    lines,
                    label,
                    count,
                    excluded_line_indexes=row_line_indexes,
                )
            )
        coverage = {
            "random_sequence_container_count": 1,
            "actor_mixer_count": 2,
            "work_unit_count": 2,
            "default_work_unit_count": 1,
            "raw_row_count": 5,
            "take": 8,
            "bound_reached": False,
            "summary_line_indexes": sorted(summary_lines),
            "truncation_claimed": campaign._campaign_claims_ancestor_truncation(
                final_response
            ),
        }
        return required, excluded, [], ancestors, coverage, order
    assert rule["final_answer_policy"] == "paired_path_rows"
    lines = final_response.splitlines()
    required = []
    for key in rule["exact_expected_keys"]:
        matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in campaign._campaign_path_token_offsets(
                line, by_key[key]["path"]
            )
        ]
        required.append(
            {
                "key": key,
                "path": by_key[key]["path"],
                "occurrence_count": len(matches),
                "first_line": matches[0][0] if matches else None,
            }
        )
    excluded = [
        {
            "key": key,
            "path": by_key[key]["path"],
            "occurrence_count": sum(
                len(campaign._campaign_path_token_offsets(line, by_key[key]["path"]))
                for line in lines
            ),
        }
        for key in rule["excluded_keys"]
    ]
    id_to_key = {row["id"]: key for key, row in by_key.items()}
    paired = []
    answer_order = []
    for child_key in rule["expected_order_keys"]:
        child = by_key[child_key]
        parent_key = id_to_key.get(child["parent_id"])
        if child["type"] != "Sound" or parent_key not in rule["exact_expected_keys"]:
            continue
        parent = by_key[parent_key]
        matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in campaign._campaign_path_token_offsets(line, child["path"])
        ]
        assert len(matches) == 1
        line_index = matches[0][0]
        line = lines[line_index]
        volume = float(
            next(
                item["value"]
                for item in child["properties"]
                if item["name"] == "Volume"
            )
        )
        paired.append(
            {
                "child_key": child_key,
                "parent_key": parent_key,
                "parent_path": parent["path"],
                "child_path": child["path"],
                "language": child["source_language"],
                "volume": volume,
                "notes": child["notes"],
                "line_index": line_index,
                "line_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
                "parent_path_count": len(
                    campaign._campaign_path_token_offsets(line, parent["path"])
                ),
                "child_path_count": len(
                    campaign._campaign_path_token_offsets(line, child["path"])
                ),
                "language_present": child["source_language"].casefold()
                in line.casefold(),
                "volume_values": [
                    float(value)
                    for value in campaign._OBJECT_ANSWER_NUMBER_RE.findall(line)
                ],
                "notes_present": child["notes"].casefold() in line.casefold(),
                "unexpected_languages": [],
                "unexpected_notes": [],
            }
        )
        answer_order.append(child_key)
    return required, excluded, paired, [], None, answer_order


def _synthetic_object_mutation_verification(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    before = plan["live_binding"]["before_snapshot"]
    before_by_key = {row["key"]: dict(row) for row in before["objects"]}
    expected_rule, identity_rule, _oracle_rule = plan["delta_rules"]
    expected_objects = expected_rule["expected_objects"]
    before_ids = {row["id"] for row in before["objects"]}
    resolved: dict[str, dict[str, Any]] = {}

    for index, expected in enumerate(expected_objects, start=1):
        key = expected["key"]
        previous = before_by_key.get(key)
        if expected["identity_policy"] in {"preserve", "borrowed_snapshot"}:
            if previous is None:
                raise AssertionError("synthetic preserve object lacks before row")
            row = json.loads(json.dumps(previous))
        else:
            row = {
                "key": key,
                "id": f"{{aaaaaaaa-aaaa-aaaa-aaaa-{index:012d}}}",
                "name": expected["requested_name"],
                "type": expected["object_type"],
                "path": expected["path"] or "",
                "parent_id": None,
                "notes": None,
                "properties": [],
                "references": [],
                "source_language": None,
                "is_included": None,
                "children_count": len(expected["children"]),
                "active_source_id": None,
                "active_source_name": None,
                "active_source_path": None,
            }
        resolved[key] = row

    for expected in expected_objects:
        key = expected["key"]
        row = resolved[key]
        previous = before_by_key.get(key)
        parent = resolved.get(expected["parent_key"]) or before_by_key.get(
            expected["parent_key"]
        )
        if parent is not None:
            row["parent_id"] = parent["id"]
            if not row["path"]:
                row["path"] = f"{parent['path']}\\{row['name']}"
        elif not row["path"] and expected["parent_path"] is not None:
            row["path"] = f"{expected['parent_path']}\\{row['name']}"
        row["children_count"] = len(expected["children"])
        properties = {item["name"]: item["value"] for item in row["properties"]}
        references = {
            item["name"]: item["target_id"] for item in row["references"]
        }
        for field in expected["fields"]:
            name, mode, value = field["name"], field["mode"], field["value"]
            if mode == "object_key_id":
                target = resolved.get(str(value)) or before_by_key.get(str(value))
                if target is None:
                    raise AssertionError("synthetic reference target is missing")
                references[name] = target["id"]
            elif mode == "derived_children_count":
                row["children_count"] = len(expected["children"])
            elif mode == "sealed_fixture_snapshot":
                if previous is None:
                    raise AssertionError("synthetic sealed field lacks before row")
            elif name.startswith("@"):
                properties[name[1:]] = value
            elif name in {
                "name",
                "type",
                "path",
                "notes",
                "source_language",
                "is_included",
            }:
                row[name] = value
            elif name == "audioSource:language":
                row["source_language"] = value
            elif name == "isIncluded":
                row["is_included"] = value
            elif name == "parent":
                row["parent_id"] = value
            elif name == "childrenCount":
                row["children_count"] = value
            else:
                references[name] = value
        row["properties"] = [
            {"name": name, "value": value}
            for name, value in sorted(properties.items())
        ]
        row["references"] = [
            {"name": name, "target_id": value}
            for name, value in sorted(references.items())
        ]
        if row["id"] in before_ids and expected["identity_policy"] in {
            "new",
            "new_renamed",
            "replace_with_new",
        }:
            raise AssertionError("synthetic new GUID collided with before snapshot")

    removed_keys = list(identity_rule["removed_keys"])
    protected_keys = list(identity_rule["protected_snapshot_keys"])
    after_rows = [
        row
        for key, row in before_by_key.items()
        if key not in removed_keys and key not in resolved
    ] + list(resolved.values())
    before_overrides = dict(before.get("override_output_rows", []))
    override_types = {"ActorMixer", "RandomSequenceContainer", "Sound"}
    after_override_rows = []
    for row in after_rows:
        key = row["key"]
        if row["type"] not in override_types:
            override_value = None
        elif (
            plan["static_expectation"]["scenario_id"] == "OBJ22-F-SET-03"
            and key.endswith("_child")
        ):
            override_value = before_overrides.get(key, False)
        elif any(
            reference.get("name") == "OutputBus"
            for reference in row.get("references", [])
        ):
            override_value = True
        else:
            override_value = before_overrides.get(key, False)
        after_override_rows.append([key, override_value])
    after_payload = {
        "objects": after_rows,
        "absent_paths": [],
        "sibling_prefix_rows": [],
        "override_output_rows": after_override_rows,
    }
    after = {
        **after_payload,
        "digest": campaign._canonical_sha256(after_payload),
    }
    protected = {key: before_by_key[key] for key in protected_keys}
    return {
        "phase": "after",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": before,
            "after": after,
            "resolved": resolved,
            "expected_resolved_keys": [item["key"] for item in expected_objects],
            "removed_keys": removed_keys,
            "removed_readback": {key: [] for key in removed_keys},
            "protected_keys": protected_keys,
            "protected_before": protected,
            "protected_after": protected,
        },
    }


def _synthetic_set03_intrinsic_verification(
    tmp_path: Path,
    *,
    child_override_output: bool = False,
):
    case_id = "OBJ22-F-SET-03"
    recipe = build_object_heavy_v3_recipe(case_id)
    scenario = _Scenario(
        case_id,
        "ak.wwise.core.object.set",
        "synthetic SET03",
        protocol="transaction",
    )
    protocol = build_transaction_protocol([recipe.request.as_dict()])
    before = _synthetic_object_before(
        recipe,
        set03_child_override_output=child_override_output,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        (),
    )
    verification = _synthetic_object_mutation_verification(
        sections.writer_kwargs()
    )
    evidence = verification["evidence"]
    evidence["protected_after"] = copy.deepcopy(evidence["protected_after"])
    target_by_child = {
        "day_child": evidence["protected_before"]["ambience_bus"]["id"],
        "night_child": evidence["protected_before"]["ambience_bus"]["id"],
        "storm_child": evidence["protected_before"]["weather_bus"]["id"],
    }
    for key, target_id in target_by_child.items():
        parent = evidence["resolved"][key.removesuffix("_child")]
        evidence["protected_after"][key]["properties"] = copy.deepcopy(
            parent["properties"]
        )
        evidence["protected_after"][key]["references"] = [
            {"name": "OutputBus", "target_id": target_id}
        ]
    before_overrides = dict(evidence["before"]["override_output_rows"])
    after_overrides = dict(evidence["after"]["override_output_rows"])
    comparisons = {}
    for key, before_row in evidence["protected_before"].items():
        after_row = evidence["protected_after"][key]
        ignored = (
            ["@Volume", "@Pitch", "OutputBus"]
            if key in target_by_child
            else []
        )
        before_projection = campaign._campaign_object_intrinsic_projection(
            before_row,
            ignored_derived_fields=ignored,
        )
        after_projection = campaign._campaign_object_intrinsic_projection(
            after_row,
            ignored_derived_fields=ignored,
        )
        comparisons[key] = {
            "override_output_before": before_overrides[key],
            "override_output_after": after_overrides[key],
            "ignored_derived_fields": ignored,
            "before_projection": before_projection,
            "after_projection": after_projection,
            "passed": before_projection == after_projection,
        }
    evidence["protected_comparisons"] = comparisons
    return sections, verification


@pytest.mark.parametrize("child_override_output", (False, True))
def test_campaign_object_archive_accepts_strict_set03_intrinsic_projection(
    tmp_path: Path,
    child_override_output: bool,
) -> None:
    sections, verification = _synthetic_set03_intrinsic_verification(
        tmp_path,
        child_override_output=child_override_output,
    )

    validate_object_archived_verification(sections, verification)
    campaign._validate_heavy_v3_object_oracle(
        verification,
        api="ak.wwise.core.object.set",
        scenario_id="OBJ22-F-SET-03",
        primary_count=1,
        expected_final_response_sha256="0" * 64,
        final_response="",
        gateway_payload=None,
        label="synthetic SET03",
    )
    for key in ("day_child", "night_child", "storm_child"):
        comparison = verification["evidence"]["protected_comparisons"][key]
        assert comparison["override_output_before"] is child_override_output
        assert comparison["override_output_after"] is child_override_output
        assert "OutputBus" in comparison["ignored_derived_fields"]
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="protected ignored fields are not exact inherited values",
    ):
        campaign._validate_heavy_v3_object_oracle(
            verification,
            api="ak.wwise.core.object.set",
            scenario_id="OBJ22-F-SET-01",
            primary_count=1,
            expected_final_response_sha256="0" * 64,
            final_response="",
            gateway_payload=None,
            label="cross-bound synthetic SET03",
        )


def test_campaign_object_archive_keeps_legacy_exact_protected_evidence(
    tmp_path: Path,
) -> None:
    case_id = "OBJ22-F-SET-01"
    recipe = build_object_heavy_v3_recipe(case_id)
    scenario = _Scenario(
        case_id,
        "ak.wwise.core.object.set",
        "synthetic SET01",
        protocol="transaction",
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        build_transaction_protocol([recipe.request.as_dict()]),
        _synthetic_object_before(recipe),
        (),
    )
    verification = _synthetic_object_mutation_verification(
        sections.writer_kwargs()
    )
    evidence = verification["evidence"]
    before_overrides = dict(evidence["before"]["override_output_rows"])
    after_overrides = dict(evidence["after"]["override_output_rows"])
    evidence["protected_comparisons"] = {
        key: {
            "override_output_before": before_overrides[key],
            "override_output_after": after_overrides[key],
            "ignored_derived_fields": [],
            "before_projection": copy.deepcopy(before),
            "after_projection": copy.deepcopy(evidence["protected_after"][key]),
            "passed": before == evidence["protected_after"][key],
        }
        for key, before in evidence["protected_before"].items()
    }

    validate_object_archived_verification(sections, verification)
    campaign._validate_heavy_v3_object_oracle(
        verification,
            api="ak.wwise.core.object.set",
            scenario_id=case_id,
            primary_count=1,
            expected_final_response_sha256="0" * 64,
        final_response="",
        gateway_payload=None,
        label="synthetic legacy SET01",
    )


def test_get04_campaign_oracle_binds_duplicate_broker_rows_and_final_summary(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    unit = _unit(4)
    root = tmp_path / "matrix-get04"
    _write_matrix_evidence(
        root,
        options=options,
        units=(unit,),
        statuses=("PASS",),
    )
    campaign.validate_heavy_v3_child_run(
        root,
        expected_units=(unit,),
        options=options,
        returncode=0,
    )
    scenario_root = root / "scenarios" / f"001-{unit.unit_id}"
    outcome = json.loads(
        (scenario_root / "outcome.json").read_text(encoding="utf-8")
    )
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    task_root = scenario_root / "evidence" / "codex-task"
    task_result = json.loads(
        (task_root / "task-result.json").read_text(encoding="utf-8")
    )
    gateway_payload = next(
        record["payload"]
        for record in task_result["broker"]["records"]
        if record["step_name"] == "query-object"
    )
    final_response = (
        task_root / "turns" / "turn-01" / "final.txt"
    ).read_text(encoding="utf-8").rstrip("\n")

    campaign._validate_object_query_gateway_payload(
        proof,
        gateway_payload=gateway_payload,
        label="synthetic GET04",
    )
    campaign._validate_archived_deduplicated_parent_answer(
        proof,
        final_response=final_response,
        label="synthetic GET04",
    )
    r62_response = (
        final_response
        + "\n直接子对象总数为 12（此数包含所有子对象，不等同于已确认的 Sound 数）。"
    )
    campaign._validate_archived_deduplicated_parent_answer(
        proof,
        final_response=r62_response,
        label="synthetic GET04 r62",
    )
    for index, disclosure in enumerate(
        (
            "本次返回 10 条，达到 take=10 上限，不能证明没有更多结果。",
            "当前 10 条正好等于查询边界；若要确认完整集合，需要提高上限继续查询。",
            "The query returned 10 rows, hit take=10; this cannot prove there are no more.",
            "若要确认全部结果，需提高 take 上限后继续查询。",
        ),
        start=1,
    ):
        equivalent = final_response.replace(
            "10 条上限已触及，结果可能不完整。",
            disclosure,
        )
        campaign._validate_archived_deduplicated_parent_answer(
            proof,
            final_response=equivalent,
            label=f"synthetic GET04 equivalent {index}",
        )

    for disclosure in (
        "查询使用 take=10。",
        "本次未达到 10 条上限，结果完整，没有更多。",
        "本次返回 10 条。",
        "10 条上限已触及，结果完整。",
    ):
        omitted = final_response.replace(
            "10 条上限已触及，结果可能不完整。",
            disclosure,
        )
        with pytest.raises(CampaignEvidenceError, match="coverage summary"):
            campaign._validate_archived_deduplicated_parent_answer(
                proof,
                final_response=omitted,
                label="synthetic GET04 missing disclosure",
            )

    reordered = copy.deepcopy(gateway_payload)
    reordered["objects"][0], reordered["objects"][3] = (
        reordered["objects"][3],
        reordered["objects"][0],
    )
    with pytest.raises(CampaignEvidenceError, match="primary identities"):
        campaign._validate_object_query_gateway_payload(
            proof,
            gateway_payload=reordered,
            label="synthetic GET04",
        )

    wrong_field = copy.deepcopy(gateway_payload)
    wrong_field["objects"][0]["childrenCount"] = 99
    with pytest.raises(CampaignEvidenceError, match="sealed fields"):
        campaign._validate_object_query_gateway_payload(
            proof,
            gateway_payload=wrong_field,
            label="synthetic GET04",
        )

    overclaim = final_response.replace(
        "确认覆盖 10 个直接子 Sound", "确认覆盖 12 个直接子 Sound"
    )
    with pytest.raises(CampaignEvidenceError, match="coverage summary"):
        campaign._validate_archived_deduplicated_parent_answer(
            proof,
            final_response=overclaim,
            label="synthetic GET04",
        )

    positive_then_unrelated_negation = (
        final_response + "\n确认覆盖 12 个 Sound，但这不是最终完整结果。"
    )
    with pytest.raises(CampaignEvidenceError, match="coverage summary"):
        campaign._validate_archived_deduplicated_parent_answer(
            proof,
            final_response=positive_then_unrelated_negation,
            label="synthetic GET04",
        )


def test_get05_campaign_oracle_binds_sealed_ancestor_rows_and_final_summary(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    unit = _unit(5)
    root = tmp_path / "matrix-get05"
    _write_matrix_evidence(
        root,
        options=options,
        units=(unit,),
        statuses=("PASS",),
    )
    campaign.validate_heavy_v3_child_run(
        root,
        expected_units=(unit,),
        options=options,
        returncode=0,
    )
    scenario_root = root / "scenarios" / f"001-{unit.unit_id}"
    outcome = json.loads(
        (scenario_root / "outcome.json").read_text(encoding="utf-8")
    )
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    task_root = scenario_root / "evidence" / "codex-task"
    task_result = json.loads(
        (task_root / "task-result.json").read_text(encoding="utf-8")
    )
    gateway_payload = next(
        record["payload"]
        for record in task_result["broker"]["records"]
        if record["step_name"] == "query-object"
    )
    final_response = (
        task_root / "turns" / "turn-01" / "final.txt"
    ).read_text(encoding="utf-8").rstrip("\n")

    campaign._validate_object_query_gateway_payload(
        proof,
        gateway_payload=gateway_payload,
        label="synthetic GET05",
    )
    campaign._validate_archived_ordered_ancestor_answer(
        proof,
        final_response=final_response,
        label="synthetic GET05",
    )

    reordered_payload = copy.deepcopy(gateway_payload)
    reordered_payload["objects"][0], reordered_payload["objects"][3] = (
        reordered_payload["objects"][3],
        reordered_payload["objects"][0],
    )
    reordered_proof = copy.deepcopy(proof)
    reordered_proof["observed_keys"][0], reordered_proof["observed_keys"][3] = (
        reordered_proof["observed_keys"][3],
        reordered_proof["observed_keys"][0],
    )
    campaign._validate_object_query_gateway_payload(
        reordered_proof,
        gateway_payload=reordered_payload,
        label="synthetic GET05 unordered broker",
    )

    wrong_field = copy.deepcopy(gateway_payload)
    wrong_field["objects"][0]["notes"] = "tampered"
    with pytest.raises(CampaignEvidenceError, match="sealed fields"):
        campaign._validate_object_query_gateway_payload(
            proof,
            gateway_payload=wrong_field,
            label="synthetic GET05",
        )

    duplicate = copy.deepcopy(gateway_payload)
    duplicate["objects"][1] = copy.deepcopy(duplicate["objects"][0])
    duplicate_proof = copy.deepcopy(proof)
    duplicate_proof["observed_keys"][1] = duplicate_proof["observed_keys"][0]
    with pytest.raises(CampaignEvidenceError, match="primary identities"):
        campaign._validate_object_query_gateway_payload(
            duplicate_proof,
            gateway_payload=duplicate,
            label="synthetic GET05",
        )

    lines = final_response.splitlines()
    before_by_key = {
        row["key"]: row for row in proof["before"]["objects"]
    }
    decoy = before_by_key["q5_decoy_player"]
    tampered_answers = {
        "row order": "\n".join([*lines[:3], lines[4], lines[3], *lines[5:]]),
        "row type": final_response.replace(
            "RandomSequenceContainer", "Sound", 1
        ),
        "row childrenCount": final_response.replace(
            "| 2 | query05 root |", "| 99 | query05 root |"
        ),
        "row ordinal": final_response.replace(
            "| 1 | Movement |", "| 9 | Movement |", 1
        ),
        "row notes": final_response.replace("movement owner", "wrong notes", 1),
        "missing Default Work Unit": "\n".join(
            line
            for line in lines
            if "Default Work Unit" not in line or "唯一" in line
        ),
        "same-name decoy": final_response
        + f"\n| {decoy['name']} | {decoy['id']} | {decoy['type']} | "
        + f"`{decoy['path']}` | {decoy['children_count']} | {decoy['notes']} |",
        "Project row": final_response
        + "\n| Project | {eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee} | Project | `\\Project` | 1 | 无备注 |",
        "wrong summary": final_response.replace(
            "2 个 Actor Mixer", "3 个 Actor Mixer"
        ),
        "unknown type alias": final_response.replace(
            "Random Container", "Random Group"
        ),
        "false truncation": final_response + "\n结果已截断。",
    }
    for name, tampered in tampered_answers.items():
        with pytest.raises(CampaignEvidenceError):
            campaign._validate_archived_ordered_ancestor_answer(
                proof,
                final_response=tampered,
                label=f"synthetic GET05 {name}",
            )


def _synthetic_audio_snapshot(
    *, scenario_id: str, io_root: Path, mtime_ns: int
) -> dict[str, Any]:
    object_path = "\\Actor-Mixer Hierarchy\\Default Work Unit\\Synthetic"
    converted_path = str(io_root / "Windows" / "synthetic.wem")
    original = {
        "path": str(io_root.parent / "assets" / "synthetic.wav"),
        "present": True,
        "size": 64,
        "sha256": "1" * 64,
        "mtime_ns": 1,
    }
    converted = {
        "path": converted_path,
        "present": True,
        "size": 32,
        "sha256": "2" * 64,
        # Baseline evidence is immutable across before/after snapshots.  The
        # current artifact copy below receives the requested phase mtime.
        "mtime_ns": 10,
    }
    conversion_xml = {
        "path": str(io_root.parent / "project" / "Conversion Settings.wwu"),
        "present": True,
        "size": 16,
        "sha256": "3" * 64,
        "mtime_ns": 1,
    }
    _presets, profiles = _synthetic_audio_components_and_profiles(scenario_id)
    baseline_artifact = {
        "object_path": object_path,
        "object_id": "{11111111-1111-1111-1111-111111111111}",
        "source_id": "{33333333-3333-3333-3333-333333333333}",
        "source_key": "synthetic",
        "platform": "Windows",
        "language": "SFX",
        "conversion_id": "{44444444-4444-4444-4444-444444444444}",
        "conversion_name": profiles[0].name,
        "original_path": original["path"],
        "original_file": original,
        "converted_path": converted_path,
        "file": converted,
        "codec": "PCM",
        "sample_rate": 48000,
    }
    artifact = copy.deepcopy(baseline_artifact)
    if mtime_ns == 10:
        artifact["file"] = {
            "path": converted_path,
            "present": False,
            "size": None,
            "sha256": None,
            "mtime_ns": None,
        }
        artifact["codec"] = None
        artifact["sample_rate"] = None
    else:
        artifact["file"]["mtime_ns"] = mtime_ns
    snapshot = {
        "artifacts": [artifact],
        "baseline_artifacts": [baseline_artifact],
        "input_files": [original],
        "originals_files": [original],
        "authoring_files": [],
        "conversion_xml": conversion_xml,
        "output_tree": ([] if mtime_ns == 10 else [artifact["file"]]),
        "baseline_artifact_paths": [converted_path],
        "volatile_cache_files": [
            {"path": path, "present": False, "size": None}
            for path in audio_conversion_volatile_cache_paths(io_root)
        ],
    }
    digest_payload = {
        "artifacts": snapshot["artifacts"],
        "baseline_artifacts": snapshot["baseline_artifacts"],
        "inputs": snapshot["input_files"],
        "originals": snapshot["originals_files"],
        "authoring_files": snapshot["authoring_files"],
        "conversion_xml": snapshot["conversion_xml"],
        "output_tree": snapshot["output_tree"],
        "baseline_artifact_paths": snapshot["baseline_artifact_paths"],
    }
    return {**snapshot, "digest": campaign._canonical_sha256(digest_payload)}


def _synthetic_audio_oracle(
    *,
    unit: _Unit,
    scenario_root: Path,
    broker_records: Sequence[Mapping[str, Any]],
    business_oracle_plan_sha256: str,
) -> dict[str, Any]:
    io_root = scenario_root / "owned" / "io"
    operation_request = _synthetic_audio_operation_request(unit, io_root=io_root)
    before = _synthetic_audio_snapshot(
        scenario_id=unit.unit_id, io_root=io_root, mtime_ns=10
    )
    after = _synthetic_audio_snapshot(
        scenario_id=unit.unit_id, io_root=io_root, mtime_ns=20
    )
    verify_payloads = [
        record.get("payload")
        for record in broker_records
        if record.get("step_name") == "tx01.verify"
    ]
    verify_payload_sha256 = (
        campaign._canonical_sha256(verify_payloads[0])
        if len(verify_payloads) == 1 and isinstance(verify_payloads[0], Mapping)
        else "5" * 64
    )
    verification = {
        "phase": "after",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": before,
            "after": after,
            "target_slots": 1,
            "observed_target_paths": [after["artifacts"][0]["converted_path"]],
            "after_digest": after["digest"],
            "volatile_cache_files_before": before["volatile_cache_files"],
            "volatile_cache_files_after": after["volatile_cache_files"],
            "volatile_cache_changed_paths": [],
            "byte_change_required_paths": [],
            "operation_request": operation_request,
            "operation_request_sha256": campaign._canonical_sha256(operation_request),
            "verify_request_sha256": campaign._canonical_sha256(operation_request),
            "verify_payload_sha256": verify_payload_sha256,
        },
    }
    return {
        "contract": campaign.HEAVY_V3_ORACLE_CONTRACT,
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "api": unit.scenario.api,
        "runner": "project",
        "business_oracle_plan_sha256": business_oracle_plan_sha256,
        "verification": verification,
    }


def _synthetic_cli_tree_sha256(files: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda row: str(row["relative_path"])):
        digest.update(str(item["relative_path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _synthetic_cli_changed_tree(tree: Mapping[str, Any]) -> dict[str, Any]:
    changed = json.loads(json.dumps(tree))
    files = changed["files"]
    if files:
        files[0]["sha256"] = "f" * 64
        files[0]["mtime_ns"] = int(files[0]["mtime_ns"]) + 1
    else:
        files.append(
            {
                "path": str(Path(changed["root"]) / "changed.wproj"),
                "relative_path": "changed.wproj",
                "size": 1,
                "sha256": "f" * 64,
                "mtime_ns": 1,
            }
        )
    files.sort(key=lambda row: str(row["relative_path"]))
    changed["sha256"] = _synthetic_cli_tree_sha256(files)
    return changed


def _append_synthetic_cli_file(
    tree: dict[str, Any],
    relative_path: str,
    payload: bytes,
) -> None:
    tree["files"].append(
        {
            "path": str(Path(tree["root"]) / relative_path),
            "relative_path": relative_path,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mtime_ns": 1,
        }
    )
    tree["files"].sort(key=lambda row: str(row["relative_path"]))
    tree["sha256"] = _synthetic_cli_tree_sha256(tree["files"])


def _synthetic_convert_verification_with_side_effects(
    sections: Any,
) -> dict[str, Any]:
    verification = _synthetic_cli_verification(sections)
    asset_tree = verification["after"]["asset_tree"]
    wav = next(
        row for row in asset_tree["files"]
        if row["relative_path"].casefold().endswith(".wav")
    )
    akd_relative = PurePosixPath(wav["relative_path"]).with_suffix(".akd").as_posix()
    _append_synthetic_cli_file(
        asset_tree,
        akd_relative,
        b"\r\x00\x00\x00" + b"sealed-akd" * 3,
    )

    project_tree = verification["after"]["project_tree"]
    project = next(
        row for row in project_tree["files"]
        if row["relative_path"].casefold().endswith(".wproj")
    )
    _append_synthetic_cli_file(
        project_tree,
        ".cache/CacheVersion",
        b"F\x00\x00\x00",
    )
    _append_synthetic_cli_file(
        project_tree,
        f"{PurePosixPath(project['relative_path']).stem}.crossover.wsettings",
        b'<WwiseDocument Type="UserProjectSettings"/>',
    )
    return verification


def _synthetic_cli_verification(sections: Any) -> dict[str, Any]:
    static = sections.static_expectation
    live = sections.live_binding
    before = json.loads(json.dumps(live["before_snapshot"]))
    after = json.loads(json.dumps(before))
    operation = static["operation"]
    if operation in {"convertExternalSource", "generateSoundbank"}:
        output_tree = after["output_tree"]
        output_root = Path(output_tree["root"])
        rows = {item["path"]: item for item in output_tree["files"]}
        rebuild_seeds = static["asset_spec"]["fixture_manifest"].get(
            "rebuild_seeds"
        ) if operation == "generateSoundbank" else None
        if rebuild_seeds is not None:
            cache_binding = static["asset_spec"]["request"]["path_bindings"]["cache"]
            cache_root = Path(live["root_bindings"][cache_binding["root_key"]])
            cache_path = (
                cache_root
                / cache_binding["relative_path"]
                / rebuild_seeds["cache"]["relative_path"]
            ).resolve(strict=False)
            rows.pop(str(cache_path), None)
        for index, expected in enumerate(static["expected_outputs"], start=1):
            path = Path(expected["path"])
            previous = rows.get(str(path))
            rows[str(path)] = {
                "path": str(path),
                "relative_path": path.relative_to(output_root).as_posix(),
                "size": 16 + index,
                "sha256": f"{index:x}" * 64,
                "mtime_ns": int((previous or {}).get("mtime_ns", 0)) + 1,
            }
        output_tree["files"] = sorted(
            rows.values(), key=lambda row: str(row["relative_path"])
        )
        output_tree["sha256"] = _synthetic_cli_tree_sha256(
            output_tree["files"]
        )
    elif operation == "tabDelimitedImport":
        after["project_tree"] = _synthetic_cli_changed_tree(
            after["project_tree"]
        )
        before_objects = {row["path"]: row for row in before["objects"]}
        objects = {row["path"]: row for row in after["objects"]}
        source_bindings = {
            row["source_key"]: row for row in live["tab_source_bindings"]
        }
        generated_ids: dict[str, str] = {}
        for index, expected in enumerate(
            static["asset_spec"]["expected"]["objects"], start=1
        ):
            path = str(expected["path"])
            previous = before_objects.get(path)
            if expected["guid_policy"] == "preserved" and previous is not None:
                object_id = previous["object_id"]
            else:
                object_id = f"{{AAAAAAAA-AAAA-AAAA-AAAA-{index:012X}}}"
            source_key = str(expected.get("source_key") or "")
            source_hash = source_bindings[source_key]["sha256"]
            row = {
                "path": path,
                "object_id": object_id,
                "object_type": expected["type"],
                "name": path.rsplit("\\", 1)[-1],
                "parent_id": None,
                "language": expected["language"],
                "source_path": None,
                "source_sha256": source_hash,
                "notes": None,
                "short_id": None,
            }
            objects[path] = row
            generated_ids[path] = object_id
        after["objects"] = list(objects.values())
        events = {row["path"]: row for row in after["events"]}
        for index, expected in enumerate(
            static["asset_spec"]["expected"]["objects"], start=1
        ):
            if not expected.get("event"):
                continue
            path = "\\Events\\Default Work Unit\\" + str(expected["event"])
            events[path] = {
                "path": path,
                "object_id": f"{{BBBBBBBB-BBBB-BBBB-BBBB-{index:012X}}}",
                "action_ids": [f"{{CCCCCCCC-CCCC-CCCC-CCCC-{index:012X}}}"],
                "target_ids": [generated_ids[str(expected["path"])]],
                "action_types": [1],
            }
        after["events"] = list(events.values())
    elif operation == "migrate":
        after["project_tree"] = _synthetic_cli_changed_tree(
            after["project_tree"]
        )
        after["project_version"] = "v2022.1.0"
    else:  # pragma: no cover - the compiler closes this set
        raise AssertionError(operation)
    return {
        "scenario_id": static["scenario_id"],
        "phase": "after",
        "passed": True,
        "failures": [],
        "before": before,
        "after": after,
    }


def _synthetic_soundbank_verification(sections: Any) -> dict[str, Any]:
    static = sections.static_expectation
    live = sections.live_binding
    before = json.loads(json.dumps(live["before_snapshot"]))
    if static["zero_dispatch_error_code"] is not None:
        return {
            "scenario_id": static["scenario_id"],
            "phase": "zero_dispatch",
            "passed": True,
            "failures": [],
            "before": before,
            "after": json.loads(json.dumps(before)),
        }
    after = json.loads(json.dumps(before))
    after["output_files"][0]["sha256"] = "f" * 64
    after["output_files"][0]["mtime_ns"] += 1
    artifact_verification = {
        "scenario_id": static["scenario_id"],
        "phase": (
            "topic_artifacts" if static["api"] == SOUNDBANK_TOPIC else "after_execution"
        ),
        "passed": True,
        "failures": [],
        "before": before,
        "after": after,
    }
    if static["api"] != SOUNDBANK_TOPIC:
        return artifact_verification
    expected_keys = list(sections.delta_rules[0]["expected_event_keys"])
    return {
        "topic": {
            "scenario_id": static["scenario_id"],
            "passed": True,
            "failures": [],
            "observed_keys": expected_keys,
            "expected_keys": expected_keys,
        },
        "artifacts": artifact_verification,
    }


def _write_passing_project_outcome(
    scenario_root: Path,
    *,
    unit: _Unit,
    thread_id: str,
    options: campaign.CampaignOptions,
    visible_values: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    evidence_root = scenario_root / "evidence"
    task_root = evidence_root / "codex-task"
    broker_state = task_root / "broker" / "state"
    broker_evidence = task_root / "broker" / "evidence"
    broker_state.mkdir(parents=True)
    broker_evidence.mkdir(parents=True)
    workspace = task_root / "agent-workspace"
    workspace.mkdir(parents=True)
    skill_install = prepare_workspace_skill_install(
        workspace,
        options.skill_source,
        platform_name=(
            "nt" if options.windows_powershell_core_host is not None else "posix"
        ),
    )
    prompts = _materialized_prompts(unit, visible_values=visible_values)
    prompt_materialization, provenance, business_oracle_plan = _write_prompt_materialization(
        task_root,
        unit=unit,
        visible_values=visible_values,
    )
    protocol = provenance.protocol
    records = _synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version=unit.version,
        invocation_skill_source=skill_install,
    )
    if unit.scenario.api == "ak.wwise.core.object.get":
        _populate_synthetic_object_query_payload(
            records,
            business_oracle_plan.payload,
        )
    broker = {
        "expected_step_names": [step.name for step in protocol.steps],
        "consumed_step_names": [step.name for step in protocol.steps],
        "records": records,
        "state_directory": str(broker_state),
        "evidence_directory": str(broker_evidence),
        "runner_path": str(
            Path(os.path.abspath(os.fspath(options.skill_source / "scripts" / "run.py")))
        ),
        "terminal_state": "COMPLETE",
        "complete": True,
        "passed": True,
    }
    composer_evidence = None
    if any(
        step.subcommand.startswith("draft-")
        or step.subcommand == "preview-from-draft"
        for step in protocol.steps
    ):
        from tests.semantic.support.codex_typed_draft_evidence_v3 import (
            validate_typed_draft_evidence,
        )

        composer_evidence = validate_typed_draft_evidence(
            state_directory=broker_state,
            steps=protocol.steps,
            broker_records=records,
        )
    if unit.scenario.api == "ak.wwise.core.object.get":
        plan_payload = business_oracle_plan.payload
        final_response = _synthetic_object_final_response(plan_payload)
    else:
        final_response = "waapi-skill 已加载，操作完成。"
    grades: list[dict[str, Any]] = []
    previous_prefix = 0
    for index, prompt in enumerate(prompts, start=1):
        prefix = protocol.turn_prefix_counts[index - 1]
        turn_records = records[previous_prefix:prefix]
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        grade = {
            "index": index,
            "prompt_sha256": prompt_sha256,
            "broker_prefix_count": prefix,
            "reconciliation": {
                "passed": True,
                "observed_command_count": prefix,
                "accepted_record_count": prefix,
                "errors": [],
            },
            "common_gates": {
                key: True for key in campaign._HEAVY_V3_REQUIRED_COMMON_GATES
            },
            "errors": [],
            "passed": True,
        }
        grades.append(grade)
        turn_root = task_root / "turns" / f"turn-{index:02d}"
        turn_root.mkdir(parents=True)
        turn_final = final_response if index == len(prompts) else "预览已准备。"
        events_text = _synthetic_events(
            thread_id=thread_id,
            records=turn_records,
            final_response=turn_final,
            read_paths=(
                _synthetic_first_turn_reads(
                    options,
                    unit,
                    skill_source=_synthetic_runtime_skill_read_source(
                        options,
                        skill_install,
                    ),
                )
                if index == 1
                else ()
            ),
            windows_skill_read_source=(
                skill_install
                if options.windows_powershell_core_host is not None
                else None
            ),
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
        matrix.write_text(turn_root / "prompt.txt", prompt + "\n")
        matrix.write_text(turn_root / "events.jsonl", events_text)
        matrix.write_text(turn_root / "stderr.txt", "")
        matrix.write_text(turn_root / "final.txt", turn_final + "\n")
        matrix.write_json(turn_root / "turn-grade.json", grade)
        matrix.write_json(
            turn_root / "codex-facts.json",
            _synthetic_codex_facts(
                options=options,
                task_root=task_root,
                turn_root=turn_root,
                turn_index=index,
                prompt=prompt,
                thread_id=thread_id,
                events_text=events_text,
                protocol=protocol,
                version=unit.version,
            ),
        )
        previous_prefix = prefix
    task_result = {
            "contract": campaign.HEAVY_V3_TASK_RESULT_CONTRACT,
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "thread_id": thread_id,
            "turn_count": len(prompts),
            "passed": True,
            "prompt_materialization_sha256": hashlib.sha256(
                prompt_materialization.read_bytes()
            ).hexdigest(),
            "broker": broker,
            "turn_grades": grades,
        }
    if composer_evidence is not None:
        task_result["composer_evidence"] = composer_evidence
    matrix.write_json(
        task_root / "task-result.json",
        task_result,
    )
    source_hash = {
        "algorithm": "sha256",
        "strategy": "full",
        "digest": "c" * 64,
        "file_count": 2,
        "bytes_hashed": 100,
    }
    lifecycle = {
        "contract": campaign.HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT,
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "requested_status": "PASS",
        "final_status": "PASS",
        "sandbox_retained": False,
        "source_hash_before": source_hash,
        "source_hash_after": source_hash,
        "source_mtime_before_ns": 123456,
        "source_mtime_after_ns": 123456,
        "errors": [],
        "quarantine_path": None,
    }
    matrix.write_json(evidence_root / "lifecycle.json", lifecycle)
    matrix.write_json(
        evidence_root / "start.json",
        {
            "contract": campaign.HEAVY_V3_PROJECT_LIFECYCLE_CONTRACT,
            "scenario_id": unit.unit_id,
            "version": unit.version,
            "started_at": "2026-07-20T00:00:00Z",
            "source_hash_before": source_hash,
            "source_mtime_before_ns": 123456,
            "sandbox_project": str(
                scenario_root.resolve() / "owned" / "sandbox-root" / "SampleProject.wproj"
            ),
            "launch_cwd": str(
                scenario_root.resolve() / "owned" / "sandbox-root"
            ),
            "endpoint": {"host": "127.0.0.1", "port": 18080},
            "isolated_launch_environment": {},
            "owned_wine_prefix": None,
        },
    )
    shutil.rmtree(scenario_root / "owned")
    return {
        "contract": campaign.HEAVY_V3_PROJECT_OUTCOME_CONTRACT,
        "scenario_id": unit.unit_id,
        "version": unit.version,
        "status": "PASS",
        "reason": "",
        "scenario_root": str(scenario_root.resolve()),
        "task_root": str(task_root.resolve()),
        "thread_id": thread_id,
        "checks": {
            "task_passed": True,
            "first_use_intro": True,
            "final_response_nonempty": True,
            "direct_client_closed": True,
            "trusted_direct_call_count": 1,
            "primary_dispatch": {
                "api": unit.scenario.api,
                "dispatch_count": unit.scenario.primary_dispatch.count,
            },
            "business_verification": (
                _synthetic_audio_oracle(
                    unit=unit,
                    scenario_root=scenario_root,
                    broker_records=records,
                    business_oracle_plan_sha256=business_oracle_plan.sha256,
                )
                if unit.scenario.api == "ak.wwise.core.audio.convert"
                else _synthetic_object_oracle(
                    unit=unit,
                    final_response=final_response,
                    business_oracle_plan=business_oracle_plan,
                )
            ),
        },
        "lifecycle": lifecycle,
    }


def _validation(
    units: Sequence[_Unit],
    *,
    statuses: Sequence[str],
    pending: Sequence[str] = (),
    retry_categories: Sequence[str] = (),
) -> ChildValidation:
    verdicts = tuple(
        PhaseVerdict(
            session_id=unit.unit_id,
            phase=campaign.HEAVY_V3_PHASE,
            status=status,
            reason="synthetic",
            retry_category=(
                retry_categories[0]
                if status == "RETRYABLE" and retry_categories
                else None
            ),
        )
        for unit, status in zip(units, statuses, strict=True)
    )
    return ChildValidation(
        observations=tuple(
            {
                "unit_id": verdict.session_id,
                "status": verdict.status,
                "phases": [verdict.phase_row()],
            }
            for verdict in verdicts
        ),
        phase_verdicts=verdicts,
        executed_session_ids=tuple(verdict.session_id for verdict in verdicts),
        pending_session_ids=tuple(pending),
        retry_categories=tuple(retry_categories),
        summary={"synthetic": True},
    )


def test_parse_args_selects_heavy_defaults_and_preserves_v2_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex = tmp_path / ("codex.exe" if os.name == "nt" else "codex")
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    auth.write_text("{}\n", encoding="utf-8")
    live.write_text('{"versions": {}}\n', encoding="utf-8")
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda _value: codex,
    )
    root = tmp_path / "campaign"
    common = [
        "--campaign-root",
        str(root),
        "--auth-json",
        str(auth),
        "--live-config",
        str(live),
    ]
    v2 = campaign.parse_args(common)
    heavy = campaign.parse_args(
        [
            *common,
            "--profile",
            campaign.HEAVY_V3_PROFILE_ID,
            "--case-id",
            "OBJ22-F-GET-01",
            "--model",
            "gpt-5.6-terra",
            "--service-tier",
            "default",
        ]
    )

    assert v2.suite_path == matrix.DEFAULT_SUITE.resolve()
    assert heavy.suite_path == matrix.DEFAULT_V3_SUITE.resolve()
    assert heavy.case_ids == ("OBJ22-F-GET-01",)
    assert heavy.model == "gpt-5.6-terra"
    assert heavy.reasoning_effort == "medium"
    assert heavy.service_tier == "default"


@pytest.mark.parametrize("forbidden", [("--offline-only",), ("--pair-id", "pair")])
def test_parse_args_rejects_v2_only_heavy_filters(
    tmp_path: Path,
    forbidden: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit):
        campaign.parse_args(
            [
                "--campaign-root",
                str(tmp_path / "campaign"),
                "--profile",
                campaign.HEAVY_V3_PROFILE_ID,
                *forbidden,
            ]
        )


def test_heavy_child_argv_reuses_matrix_and_requests_exact_pending_cases(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(3, version="2025.1"))

    argv = campaign.build_heavy_v3_child_argv(
        options,
        units=units,
        matrix_root=tmp_path / "matrix",
    )

    assert Path(argv[1]).resolve(strict=True) == (
        campaign.REPO_ROOT / "tests" / "semantic" / "run_codex_skill_matrix.py"
    ).resolve(strict=True)
    assert argv[argv.index("--profile") + 1] == campaign.HEAVY_V3_PROFILE_ID
    assert [argv[index + 1] for index, value in enumerate(argv) if value == "--case-id"] == [
        "OBJ22-F-GET-01",
        "OBJ22-F-GET-03",
    ]
    assert "--pair-id" not in argv
    assert "--offline-only" not in argv
    assert "--overwrite" not in argv
    assert argv[argv.index("--model") + 1] == "gpt-5.6-terra"
    assert argv[argv.index("--reasoning-effort") + 1] == "medium"


def test_heavy_validator_preserves_fail_and_later_pass_observations(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2), _unit(3))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "FAIL", "PASS"),
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["unit_id"] for row in result.observations] == [
        "OBJ22-F-GET-01",
        "OBJ22-F-GET-02",
        "OBJ22-F-GET-03",
    ]
    assert [row["status"] for row in result.observations] == ["PASS", "FAIL", "PASS"]
    assert result.pending_session_ids == ()


def test_heavy_validator_rejects_passing_launch_cwd_drift(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
    )
    start_path = (
        root
        / "scenarios"
        / "001-OBJ22-F-GET-01"
        / "evidence"
        / "start.json"
    )
    start = json.loads(start_path.read_text(encoding="utf-8"))
    start["launch_cwd"] = str(start_path.parent.parent / "owned")
    matrix.write_json(start_path, start)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=0,
    )

    _assert_single_heavy_case_blocked(result, reason="project start proof is invalid")


def _assert_single_heavy_case_blocked(
    result: ChildValidation,
    *,
    reason: str,
) -> None:
    assert [row["status"] for row in result.observations] == ["BLOCKED"]
    assert reason in result.phase_verdicts[0].reason
    assert result.pending_session_ids == ()


def test_heavy_validator_isolates_post_run_error_and_accepts_other_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = tuple(_unit(index) for index in range(1, 5))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "FAIL", "PASS", "PASS"),
    )
    original = campaign._validate_heavy_v3_pass_outcome

    def fail_third_post_run_validation(
        outcome: Mapping[str, Any],
        *,
        expected_unit: Any,
        expected_row: Mapping[str, Any],
        scenario_root: Path,
        options: campaign.CampaignOptions,
    ) -> None:
        if expected_unit.unit_id == units[2].unit_id:
            raise CampaignEvidenceError("synthetic post-run validator failure")
        original(
            outcome,
            expected_unit=expected_unit,
            expected_row=expected_row,
            scenario_root=scenario_root,
            options=options,
        )

    monkeypatch.setattr(
        campaign,
        "_validate_heavy_v3_pass_outcome",
        fail_third_post_run_validation,
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["unit_id"] for row in result.observations] == [
        unit.unit_id for unit in units
    ]
    assert [row["status"] for row in result.observations] == [
        "PASS",
        "FAIL",
        "BLOCKED",
        "PASS",
    ]
    assert "synthetic post-run validator failure" in result.phase_verdicts[2].reason
    assert result.executed_session_ids == tuple(unit.unit_id for unit in units)
    assert result.pending_session_ids == ()


def test_heavy_validator_accepts_terminal_block_before_prompt_materialization(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = tuple(_unit(index) for index in range(1, 6))
    blocked_id = units[3].unit_id
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "FAIL", "FAIL", "BLOCKED"),
        stop_reason=f"blocked:{blocked_id}",
        run_errors=(f"[heavy-unit:{blocked_id}] BLOCKED: fixture preparation failed",),
    )
    _mark_pre_materialization_block(
        root,
        unit=units[3],
        sequence=4,
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["unit_id"] for row in result.observations] == [
        unit.unit_id for unit in units[:4]
    ]
    assert [row["status"] for row in result.observations] == [
        "PASS",
        "FAIL",
        "FAIL",
        "BLOCKED",
    ]
    assert result.pending_session_ids == (units[4].unit_id,)


def test_heavy_validator_accepts_one_complete_abnormal_prefix_with_pending_suffix(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2), _unit(3))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
        terminal=False,
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=130,
    )

    if [row["status"] for row in result.observations] != ["PASS"]:
        raise AssertionError(repr(result.phase_verdicts))
    assert result.pending_session_ids == ("OBJ22-F-GET-02", "OBJ22-F-GET-03")


def test_heavy_validator_blocks_abnormal_nonterminal_all_pass_snapshot(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
        terminal=False,
    )

    with pytest.raises(CampaignEvidenceError, match="real pending suffix"):
        campaign.validate_heavy_v3_child_run(
            root,
            expected_units=units,
            options=options,
            returncode=130,
        )


def test_heavy_validator_does_not_swallow_summary_error_behind_pass_rows(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
        run_errors=("synthetic infrastructure error",),
    )

    with pytest.raises(CampaignEvidenceError, match="semantic failure or block"):
        campaign.validate_heavy_v3_child_run(
            root,
            expected_units=units,
            options=options,
            returncode=1,
        )


def test_heavy_validator_rejects_shape_only_pass_outcome(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(root, options=options, units=units, statuses=("PASS",))
    scenario_root = root / "scenarios" / "001-OBJ22-F-GET-01"
    outcome_path = scenario_root / "outcome.json"
    case_path = scenario_root / "matrix-case.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    outcome["task_root"] = None
    outcome["thread_id"] = None
    outcome["checks"] = {}
    outcome["lifecycle"] = None
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["runner_outcome"] = outcome
    matrix.write_json(outcome_path, outcome)
    matrix.write_json(case_path, case)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=0,
    )

    _assert_single_heavy_case_blocked(result, reason="no task root")


def test_heavy_validator_accepts_frozen_materialized_request_prompt(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_visible_request_unit(1),)
    root = tmp_path / "matrix"
    io_root = str(
        root / "scenarios" / "001-VS24-F-AUDIO-CONVERT-01" / "owned" / "io"
    )
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
        visible_values_by_id={
            units[0].unit_id: {"io_root": io_root}
        },
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=0,
    )

    assert [row["status"] for row in result.observations] == ["PASS"], "\n".join(
        verdict.reason for verdict in result.phase_verdicts
    )
    archived = (
        root
        / "scenarios"
        / "001-VS24-F-AUDIO-CONVERT-01"
        / "evidence"
        / "codex-task"
        / "turns"
        / "turn-01"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert archived == f"请把目标音频转换到 {io_root} 并汇总。\n"


def test_heavy_validator_accepts_reviewed_confirmation_prompt(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_multi_turn_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=0,
    )

    assert [row["status"] for row in result.observations] == ["PASS"], result.phase_verdicts
    confirmation = (
        root
        / "scenarios"
        / "001-OBJ22-F-CREATE-01"
        / "evidence"
        / "codex-task"
        / "turns"
        / "turn-02"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert confirmation == units[0].turns[1].prompt + "\n"


def test_heavy_validator_replays_attested_task_install_with_canonical_bytes(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_multi_turn_unit(1),)
    group = tmp_path / "attempt" / "runs" / "heavy-v3"
    root = group / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS",),
    )
    installed = workspace_skill_install_path(
        root
        / "scenarios"
        / f"001-{units[0].unit_id}"
        / "evidence"
        / "codex-task"
        / "agent-workspace"
    )

    replaced = replace_expected_skill_symlinks(
        group,
        skill_source=options.skill_source,
        candidate_sha256=stable_tree_sha256(options.skill_source),
        platform_name=(
            "nt" if options.windows_powershell_core_host is not None else "posix"
        ),
    )

    assert replaced == (installed.relative_to(group).as_posix(),)
    assert installed.is_file() and not installed.is_symlink()
    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=0,
    )
    assert [row["status"] for row in result.observations] == ["PASS"]
    confirmation = (
        root
        / "scenarios"
        / "001-OBJ22-F-CREATE-01"
        / "evidence"
        / "codex-task"
        / "turns"
        / "turn-02"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert confirmation == units[0].turns[1].prompt + "\n"


def test_heavy_validator_blocks_prompt_and_grade_digest_rewrite(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "BLOCKED"),
        stop_reason="blocked:OBJ22-F-GET-02",
        run_errors=("[heavy-unit:OBJ22-F-GET-02] BLOCKED: synthetic",),
    )
    task_root = (
        root
        / "scenarios"
        / "001-OBJ22-F-GET-01"
        / "evidence"
        / "codex-task"
    )
    rewritten = "synthetic rewritten request"
    rewritten_sha256 = hashlib.sha256(rewritten.encode("utf-8")).hexdigest()
    prompt_path = task_root / "turns" / "turn-01" / "prompt.txt"
    matrix.write_text(prompt_path, rewritten + "\n")
    grade_path = task_root / "turns" / "turn-01" / "turn-grade.json"
    grade = json.loads(grade_path.read_text(encoding="utf-8"))
    grade["prompt_sha256"] = rewritten_sha256
    matrix.write_json(grade_path, grade)
    result_path = task_root / "task-result.json"
    task_result = json.loads(result_path.read_text(encoding="utf-8"))
    task_result["turn_grades"][0]["prompt_sha256"] = rewritten_sha256
    matrix.write_json(result_path, task_result)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == [
        "BLOCKED",
        "BLOCKED",
    ]
    assert "reviewed materialization" in result.phase_verdicts[0].reason


def test_heavy_validator_rejects_missing_live_preflight(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(root, options=options, units=units, statuses=("PASS",))
    (root / "live-preflight.json").unlink()

    with pytest.raises(CampaignEvidenceError, match="live-preflight"):
        campaign.validate_heavy_v3_child_run(
            root,
            expected_units=units,
            options=options,
            returncode=0,
        )


def test_heavy_validator_stops_at_blocked_and_keeps_remaining_pending(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2), _unit(3), _unit(4))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "BLOCKED"),
        stop_reason="blocked:OBJ22-F-GET-02",
        run_errors=("[heavy-unit:OBJ22-F-GET-02] BLOCKED: synthetic",),
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == ["PASS", "BLOCKED"]
    assert result.pending_session_ids == ("OBJ22-F-GET-03", "OBJ22-F-GET-04")


def test_heavy_validator_preserves_two_passes_exact_block_and_pending_suffix(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = tuple(_unit(index) for index in range(1, 6))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "PASS", "BLOCKED"),
        stop_reason="blocked:OBJ22-F-GET-03",
        run_errors=("[heavy-unit:OBJ22-F-GET-03] BLOCKED: synthetic",),
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["unit_id"] for row in result.observations] == [
        "OBJ22-F-GET-01",
        "OBJ22-F-GET-02",
        "OBJ22-F-GET-03",
    ]
    assert [row["status"] for row in result.observations] == [
        "PASS",
        "PASS",
        "BLOCKED",
    ]
    assert result.executed_session_ids == (
        "OBJ22-F-GET-01",
        "OBJ22-F-GET-02",
        "OBJ22-F-GET-03",
    )
    assert result.pending_session_ids == (
        "OBJ22-F-GET-04",
        "OBJ22-F-GET-05",
    )


@pytest.mark.parametrize(
    "corruption",
    ("memory_audit", "prompt_audit_digest", "skill_tree_digest"),
)
def test_heavy_validator_blocks_untrusted_pass_without_losing_other_case_records(
    tmp_path: Path,
    corruption: str,
) -> None:
    options = _options(tmp_path)
    units = tuple(_unit(index) for index in range(1, 6))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("PASS", "PASS", "BLOCKED"),
        stop_reason="blocked:OBJ22-F-GET-03",
        run_errors=("[heavy-unit:OBJ22-F-GET-03] BLOCKED: synthetic",),
    )
    facts_path = (
        root
        / "scenarios"
        / "001-OBJ22-F-GET-01"
        / "evidence"
        / "codex-task"
        / "turns"
        / "turn-01"
        / "codex-facts.json"
    )
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    if corruption == "memory_audit":
        facts["isolation_audit"]["passed"] = False
    elif corruption == "prompt_audit_digest":
        facts["prompt_audit"]["prompt_sha256"] = "not-a-sha256"
    else:
        facts["skill_tree_sha256_after"] = "0" * 64
    matrix.write_json(facts_path, facts)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == [
        "BLOCKED",
        "PASS",
        "BLOCKED",
    ]
    assert "clean memory-isolated task" in result.phase_verdicts[0].reason
    assert result.executed_session_ids == (
        "OBJ22-F-GET-01",
        "OBJ22-F-GET-02",
        "OBJ22-F-GET-03",
    )
    assert result.pending_session_ids == (
        "OBJ22-F-GET-04",
        "OBJ22-F-GET-05",
    )


@pytest.mark.parametrize("connection_lost", [False, True])
def test_heavy_cli_pass_checks_accept_both_valid_migration_shutdown_shapes(
    connection_lost: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = _cli_unit(1)
    checks = {
        "task_passed": True,
        "thread_id": "thread-1",
        "first_use_intro": True,
        "source_template_unchanged": True,
        "turn_01_response_nonempty": True,
        "turn_02_response_nonempty": True,
        "primary_dispatch": {
            "api": "ak.wwise.cli.migrate",
            "count": 1,
            "connection_lost": connection_lost,
            "connection_lost_after_dispatch": connection_lost,
        },
        "business_verification": {"passed": True, "failures": []},
    }

    monkeypatch.setattr(
        campaign,
        "_validate_heavy_v3_archived_verification",
        lambda *_args, **_kwargs: None,
    )
    campaign._validate_heavy_v3_pass_checks(
        checks,
        expected_unit=unit,
        expected_row={"api": unit.scenario.api, "runner": "cli", "version": "2022.1"},
        expected_thread_id="thread-1",
        primary_count=1,
        task_root=Path("/synthetic/task"),
        prompt_evidence=None,  # type: ignore[arg-type]
    )


def test_heavy_cli_pass_checks_reject_migration_disconnect_before_dispatch() -> None:
    unit = _cli_unit(1)
    checks = {
        "task_passed": True,
        "thread_id": "thread-1",
        "first_use_intro": True,
        "source_template_unchanged": True,
        "turn_01_response_nonempty": True,
        "primary_dispatch": {
            "api": "ak.wwise.cli.migrate",
            "count": 1,
            "connection_lost": True,
            "connection_lost_after_dispatch": False,
        },
        "business_verification": {"passed": True, "failures": []},
    }

    with pytest.raises(CampaignEvidenceError, match="disconnect proof"):
        campaign._validate_heavy_v3_pass_checks(
            checks,
            expected_unit=unit,
            expected_row={"api": unit.scenario.api, "runner": "cli", "version": "2022.1"},
            expected_thread_id="thread-1",
            primary_count=1,
            task_root=Path("/synthetic/task"),
            prompt_evidence=None,  # type: ignore[arg-type]
        )


def test_heavy_validator_maps_clean_pre_agent_quota_block_to_retryable(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2), _unit(3))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == ["RETRYABLE"], result.phase_verdicts
    assert result.phase_verdicts[0].retry_category == "quota_or_rate_limit"
    assert result.retry_categories == ("quota_or_rate_limit",)
    assert result.pending_session_ids == ("OBJ22-F-GET-02", "OBJ22-F-GET-03")


def test_heavy_validator_blocks_retryable_quota_when_business_plan_is_missing(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    (
        root
        / "scenarios"
        / "001-OBJ22-F-GET-01"
        / "evidence"
        / "business-oracle-plan.json"
    ).unlink()

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="business-oracle plan")


def test_heavy_validator_maps_clean_cli_quota_block_to_retryable(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_cli_unit(1), _cli_unit(2))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:O22-CLI-MIGRATE-01",
        run_errors=("[heavy-unit:O22-CLI-MIGRATE-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == ["RETRYABLE"]
    assert result.retry_categories == ("quota_or_rate_limit",)
    assert result.pending_session_ids == ("O22-CLI-MIGRATE-02",)


def test_heavy_validator_accepts_later_turn_quota_after_proven_prior_turn(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_multi_turn_unit(1), _unit(2))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-CREATE-01",
        run_errors=("[heavy-unit:OBJ22-F-CREATE-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
        failed_turn_index=2,
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == ["RETRYABLE"]
    assert result.retry_categories == ("quota_or_rate_limit",)
    assert result.pending_session_ids == ("OBJ22-F-GET-02",)


def test_heavy_validator_rejects_resealed_retryable_failed_prompt(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_multi_turn_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-CREATE-01",
        run_errors=("[heavy-unit:OBJ22-F-CREATE-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
        failed_turn_index=2,
    )
    task_root = (
        root
        / "scenarios"
        / "001-OBJ22-F-CREATE-01"
        / "evidence"
        / "codex-task"
    )
    prompt_path = task_root / "turns" / "turn-02" / "prompt.txt"
    rewritten = "我确认执行另一份未审核请求。"
    matrix.write_text(prompt_path, rewritten + "\n")
    sidecar_path = task_root / "infrastructure-failure.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["prompt_sha256"] = hashlib.sha256(
        rewritten.encode("utf-8")
    ).hexdigest()
    sidecar["artifact_sha256"]["turns/turn-02/prompt.txt"] = hashlib.sha256(
        prompt_path.read_bytes()
    ).hexdigest()
    matrix.write_json(sidecar_path, sidecar)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="failed-turn prompt")


def test_heavy_validator_keeps_authentication_infrastructure_blocked(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2))
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: authentication",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="authentication",
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == ["BLOCKED"]
    assert result.phase_verdicts[0].retry_category is None
    assert result.retry_categories == ()


def test_heavy_validator_rejects_retryable_quota_with_cleanup_uncertainty(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    scenario_root = root / "scenarios" / "001-OBJ22-F-GET-01"
    outcome_path = scenario_root / "outcome.json"
    case_path = scenario_root / "matrix-case.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    outcome["lifecycle"]["errors"].append("wwise-shutdown:residual process")
    matrix_case = json.loads(case_path.read_text(encoding="utf-8"))
    matrix_case["runner_outcome"] = outcome
    quarantine_path = scenario_root / "evidence" / "quarantine.json"
    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8"))
    quarantine["errors"] = list(outcome["lifecycle"]["errors"])
    matrix.write_json(
        scenario_root / "evidence" / "lifecycle.json",
        outcome["lifecycle"],
    )
    matrix.write_json(quarantine_path, quarantine)
    matrix.write_json(outcome_path, outcome)
    matrix.write_json(case_path, matrix_case)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="cleanup uncertainty")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("category", "live_readiness_before_agent_action", "unknown category"),
        ("agent_item_event_count", False, "does not prove pre-agent"),
        ("category", "timeout_before_agent_action", "typed flags"),
    ),
)
def test_heavy_validator_rejects_impossible_codex_infrastructure_shape(
    tmp_path: Path,
    field: str,
    value: Any,
    match: str,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    scenario_root = root / "scenarios" / "001-OBJ22-F-GET-01"
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    outcome["checks"]["codex_infrastructure_failure"][field] = value
    _persist_runner_outcome(scenario_root, outcome)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason=match)


def test_heavy_validator_recomputes_infrastructure_category_from_raw_evidence(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    task_root = (
        root
        / "scenarios"
        / "001-OBJ22-F-GET-01"
        / "evidence"
        / "codex-task"
    )
    turn_root = task_root / "turns" / "turn-01"
    events_path = turn_root / "events.jsonl"
    stderr_path = turn_root / "stderr.txt"
    matrix.write_text(
        events_path,
        events_path.read_text(encoding="utf-8").replace(
            "rate limit exceeded",
            "authentication failed",
        ),
    )
    matrix.write_text(stderr_path, "authentication failed\n")
    failure_path = task_root / "infrastructure-failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    for path in (events_path, stderr_path):
        relative = path.relative_to(task_root).as_posix()
        failure["artifact_sha256"][relative] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    matrix.write_json(failure_path, failure)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="cannot be reconstructed")


def test_heavy_validator_rejects_failed_turn_command_with_resealed_artifact(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    task_root = root / "scenarios" / "001-OBJ22-F-GET-01" / "evidence" / "codex-task"
    facts_path = task_root / "turns" / "turn-01" / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts["command_facts"]["commands"] = ["python scratch.py"]
    matrix.write_json(facts_path, facts)
    sidecar_path = task_root / "infrastructure-failure.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    relative = "turns/turn-01/codex-facts.json"
    sidecar["artifact_sha256"][relative] = hashlib.sha256(
        facts_path.read_bytes()
    ).hexdigest()
    matrix.write_json(sidecar_path, sidecar)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="reconstructed from events")


def test_heavy_validator_rejects_broker_advance_with_resealed_artifact(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    task_root = root / "scenarios" / "001-OBJ22-F-GET-01" / "evidence" / "codex-task"
    broker_path = task_root / "broker-evidence.json"
    broker = json.loads(broker_path.read_text(encoding="utf-8"))
    broker["consumed_step_names"] = ["synthetic-step-1"]
    broker["records"] = [
        {
            "sequence": 1,
            "step_name": "synthetic-step-1",
            "authenticated": True,
            "accepted": True,
            "succeeded": True,
            "payload_error": "",
            "payload": {"ok": True},
        }
    ]
    matrix.write_json(broker_path, broker)
    sidecar_path = task_root / "infrastructure-failure.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["artifact_sha256"]["broker-evidence.json"] = hashlib.sha256(
        broker_path.read_bytes()
    ).hexdigest()
    matrix.write_json(sidecar_path, sidecar)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="prior proven prefix")


def test_heavy_validator_rejects_failed_prior_turn_grade(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_multi_turn_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-CREATE-01",
        run_errors=("[heavy-unit:OBJ22-F-CREATE-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
        failed_turn_index=2,
    )
    grade_path = (
        root
        / "scenarios"
        / "001-OBJ22-F-CREATE-01"
        / "evidence"
        / "codex-task"
        / "turns"
        / "turn-01"
        / "turn-grade.json"
    )
    grade = json.loads(grade_path.read_text(encoding="utf-8"))
    grade["passed"] = False
    matrix.write_json(grade_path, grade)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="lacks complete")


def test_heavy_validator_rejects_retryable_lifecycle_archive_drift(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    lifecycle_path = root / "scenarios" / "001-OBJ22-F-GET-01" / "evidence" / "lifecycle.json"
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    lifecycle["source_mtime_after_ns"] += 1
    matrix.write_json(lifecycle_path, lifecycle)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="embedded lifecycle differs")


def test_heavy_validator_rejects_retryable_launch_cwd_drift(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    start_path = (
        root
        / "scenarios"
        / "001-OBJ22-F-GET-01"
        / "evidence"
        / "start.json"
    )
    start = json.loads(start_path.read_text(encoding="utf-8"))
    wrong_cwd = start_path.parent.parent / "owned"
    start["launch_cwd"] = str(wrong_cwd.resolve())
    matrix.write_json(start_path, start)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="not bound to its lifecycle")


def test_heavy_validator_rejects_retryable_quarantine_tree_drift(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    quarantine_path = root / "scenarios" / "001-OBJ22-F-GET-01" / "evidence" / "quarantine.json"
    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8"))
    quarantine["owned_tree_sha256"] = "0" * 64
    matrix.write_json(quarantine_path, quarantine)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="does not seal")


def test_heavy_validator_rejects_retryable_cli_residual_phase(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_cli_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:O22-CLI-MIGRATE-01",
        run_errors=("[heavy-unit:O22-CLI-MIGRATE-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    scenario_root = root / "scenarios" / "001-O22-CLI-MIGRATE-01"
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    outcome["lifecycle"]["phases"][0]["evidence"]["residual_pids"] = [4242]
    matrix.write_json(
        scenario_root / "evidence" / "lifecycle.json",
        outcome["lifecycle"],
    )
    _persist_runner_outcome(scenario_root, outcome)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="cleanup uncertainty")


def test_heavy_validator_rejects_retryable_cli_launch_cwd_drift(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_cli_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:O22-CLI-MIGRATE-01",
        run_errors=("[heavy-unit:O22-CLI-MIGRATE-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    scenario_root = root / "scenarios" / "001-O22-CLI-MIGRATE-01"
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    outcome["lifecycle"]["phases"][0]["evidence"]["cwd"] = str(
        scenario_root / "owned"
    )
    matrix.write_json(
        scenario_root / "evidence" / "lifecycle.json",
        outcome["lifecycle"],
    )
    _persist_runner_outcome(scenario_root, outcome)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="cleanup uncertainty")


def test_heavy_validator_rejects_retryable_topic_publisher_teardown_error(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(
        root,
        options=options,
        units=units,
        statuses=("BLOCKED",),
        stop_reason="blocked:OBJ22-F-GET-01",
        run_errors=("[heavy-unit:OBJ22-F-GET-01] BLOCKED: quota",),
    )
    _mark_codex_infrastructure_block(
        root,
        options=options,
        unit=units[0],
        sequence=1,
        category="quota_or_rate_limit",
    )
    scenario_root = root / "scenarios" / "001-OBJ22-F-GET-01"
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    outcome["checks"]["topic_publisher_teardown_error"] = "synthetic teardown"
    _persist_runner_outcome(scenario_root, outcome)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=1,
    )

    _assert_single_heavy_case_blocked(result, reason="cleanup uncertainty")


def test_heavy_validator_rejects_outcome_drift(tmp_path: Path) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    root = tmp_path / "matrix"
    _write_matrix_evidence(root, options=options, units=units, statuses=("PASS",))
    outcome_path = root / "scenarios" / "001-OBJ22-F-GET-01" / "outcome.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    outcome["status"] = "FAIL"
    matrix.write_json(outcome_path, outcome)

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=units,
        options=options,
        returncode=0,
    )

    _assert_single_heavy_case_blocked(result, reason="differs from matrix-case")


def test_heavy_fingerprint_covers_runner_model_options_and_mutable_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli 1.2.3",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())

    effective = campaign.build_heavy_v3_effective_config(
        options,
        units=units,
        required_units={units[0].unit_id: (campaign.HEAVY_V3_PHASE,)},
    )

    assert effective["candidate"]["tree_sha256"] == stable_tree_sha256(
        options.skill_source,
        exclude_names=tuple(effective["candidate"]["excluded_names"]),
    )
    assert effective["runner"]["matrix_sha256"]
    assert effective["runner"]["campaign_sha256"]
    assert effective["codex"]["model"] == "gpt-5.6-terra"
    assert effective["codex"]["allow_login_shell"] is False
    if os.name == "nt":
        assert effective["codex"]["windows_shell_backend"] == (
            campaign.WINDOWS_SHELL_BACKEND
        )
        assert set(effective["codex"]["windows_powershell_core_host"]) == {
            "edition",
            "path",
            "version",
            "native_argument_passing",
            "sha256",
        }
    else:
        assert effective["codex"]["windows_shell_backend"] is None
        assert effective["codex"]["windows_powershell_core_host"] is None
    assert effective["runtime"]["interpreter_sha256"]
    assert effective["live_config"]["sha256"]
    assert tuple(effective["live_inputs"]["versions"]) == ("2022.1",)
    assert effective["options"] == campaign.heavy_v3_immutable_options(options)
    campaign.assert_heavy_v3_effective_inputs_frozen(options, effective=effective)

    options.live_config.write_text('{"drift": true}\n', encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="live config drifted"):
        campaign.assert_heavy_v3_effective_inputs_frozen(options, effective=effective)


def test_codex_version_fingerprint_permission_error_names_stage_and_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / ".codex" / ".sandbox-bin" / "codex.exe"
    denied = PermissionError(13, "Access denied")
    denied.winerror = 5  # type: ignore[attr-defined]
    monkeypatch.setattr(
        campaign,
        "codex_process_environment",
        lambda _binary, environment, **_kwargs: dict(environment),
    )
    monkeypatch.setattr(
        campaign.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(denied),
    )

    with pytest.raises(
        campaign.CampaignConfigError,
        match=r"Codex version fingerprint probe could not execute",
    ) as captured:
        campaign._codex_version_fingerprint(binary)

    message = str(captured.value)
    assert str(binary) in message
    assert "PermissionError" in message
    assert "Access denied" in message


def test_heavy_fingerprint_binds_selected_codex_runtime_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    helper = tmp_path / "codex-resources" / "codex-command-runner.exe"
    helper.parent.mkdir()
    helper.write_text("helper-v1\n", encoding="utf-8")
    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli 1.2.3",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())
    monkeypatch.setattr(campaign, "codex_runtime_files", lambda _binary: (helper,))

    effective = campaign.build_heavy_v3_effective_config(
        options,
        units=units,
        required_units={units[0].unit_id: (campaign.HEAVY_V3_PHASE,)},
    )

    assert effective["codex"]["runtime_files"] == [
        {"path": str(helper), "sha256": sha256_file(helper)}
    ]
    helper.write_text("helper-v2\n", encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="runtime helpers drifted"):
        campaign.assert_heavy_v3_effective_inputs_frozen(
            options,
            effective=effective,
        )


def test_heavy_codex_probe_denial_precedes_campaign_root_and_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    denied = PermissionError(13, "Access denied")
    denied.winerror = 5  # type: ignore[attr-defined]
    child_started = False

    def forbidden_child(*_args: Any, **_kwargs: Any) -> None:
        nonlocal child_started
        child_started = True
        raise AssertionError("campaign child must not start after config failure")

    monkeypatch.setattr(campaign, "load_heavy_v3_campaign_units", lambda _options: units)
    monkeypatch.setattr(
        campaign.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(denied),
    )
    monkeypatch.setattr(campaign, "run_child", forbidden_child)

    with pytest.raises(campaign.CampaignConfigError) as exc_info:
        campaign.run_heavy_v3_campaign(options)

    assert str(options.codex_binary) in str(exc_info.value)
    assert options.campaign_root.exists() is False
    assert child_started is False


def test_runtime_distribution_fingerprint_permission_error_names_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = PermissionError(13, "Access denied")
    denied.winerror = 5  # type: ignore[attr-defined]
    monkeypatch.setattr(
        campaign.importlib.metadata,
        "distributions",
        lambda: (_ for _ in ()).throw(denied),
    )

    with pytest.raises(
        CampaignEvidenceError,
        match=r"runtime distributions for interpreter",
    ) as captured:
        campaign._runtime_distribution_fingerprint()

    assert sys.executable in str(captured.value)
    assert "PermissionError" in str(captured.value)


def test_heavy_fingerprint_rejects_source_project_and_launcher_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1),)
    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli 1.2.3",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())
    effective = campaign.build_heavy_v3_effective_config(
        options,
        units=units,
        required_units={units[0].unit_id: (campaign.HEAVY_V3_PHASE,)},
    )
    live = json.loads(options.live_config.read_text(encoding="utf-8"))
    project = Path(live["versions"]["2022.1"]["sample_project"])
    launcher = Path(live["versions"]["2022.1"]["wwise_console"])

    project.write_text("changed project\n", encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="source project drifted"):
        campaign.assert_heavy_v3_effective_inputs_frozen(options, effective=effective)

    project.write_text("<WwiseDocument version='2022.1'/>\n", encoding="utf-8")
    # Rebuild after restoring the project, then prove the selected launcher is
    # also an immutable campaign input rather than merely a path in live.json.
    effective = campaign.build_heavy_v3_effective_config(
        options,
        units=units,
        required_units={units[0].unit_id: (campaign.HEAVY_V3_PHASE,)},
    )
    launcher.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="launcher or immutable source"):
        campaign.assert_heavy_v3_effective_inputs_frozen(options, effective=effective)


def test_heavy_fingerprint_includes_migration_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (
        _Unit(
            unit_id="HEAVY-MIGRATE",
            version="2022.1",
            scenario=_Scenario(
                "HEAVY-MIGRATE",
                "ak.wwise.cli.migrate",
                "synthetic migration request",
            ),
        ),
    )
    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli 1.2.3",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())

    effective = campaign.build_heavy_v3_effective_config(
        options,
        units=units,
        required_units={units[0].unit_id: (campaign.HEAVY_V3_PHASE,)},
    )

    migration = effective["live_inputs"]["migration_source"]
    assert Path(migration["project_path"]).resolve(strict=True) == (
        campaign.HEAVY_V3_MIGRATION_SOURCE.resolve(strict=True)
    )
    assert migration["full_project_hash"]["strategy"] == "full"


def test_heavy_resume_verify_only_and_resume_schedule_only_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2))
    effective = {
        "candidate": {
            "tree_sha256": stable_tree_sha256(options.skill_source),
            "excluded_names": [],
        },
        "codex": {"windows_powershell_core_host": None},
        "synthetic": True,
    }
    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", options.campaign_root.parent)
    monkeypatch.setattr(campaign, "load_heavy_v3_campaign_units", lambda _options: units)
    monkeypatch.setattr(
        campaign,
        "build_heavy_v3_effective_config",
        lambda *_args, **_kwargs: effective,
    )
    monkeypatch.setattr(
        campaign,
        "assert_heavy_v3_effective_inputs_frozen",
        lambda *_args, **_kwargs: None,
    )
    child_case_ids: list[tuple[str, ...]] = []

    def child(argv: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        del cwd
        case_ids = tuple(
            argv[index + 1]
            for index, value in enumerate(argv)
            if value == "--case-id"
        )
        child_case_ids.append(case_ids)
        return subprocess.CompletedProcess(list(argv), 130, "synthetic\n", "")

    validations = iter(
        (
            _validation(
                (units[0],),
                statuses=("PASS",),
                pending=(units[1].unit_id,),
            ),
            _validation((units[1],), statuses=("PASS",)),
        )
    )
    monkeypatch.setattr(campaign, "run_child", child)
    monkeypatch.setattr(
        campaign,
        "validate_heavy_v3_child_run",
        lambda *_args, **_kwargs: next(validations),
    )

    assert campaign.run_campaign(options) == campaign.EXIT_PENDING
    assert child_case_ids == [(units[0].unit_id, units[1].unit_id)]
    assert len(list_campaign_attempts(options.campaign_root)) == 1

    path_budget = campaign._require_heavy_windows_path_budget
    monkeypatch.setattr(
        campaign,
        "_require_heavy_windows_path_budget",
        lambda *_args, **_kwargs: pytest.fail(
            "verify-only must not apply a process-cwd launch budget"
        ),
    )
    verify_only = replace(options, resume=True, verify_only=True)
    assert campaign.run_campaign(verify_only) == campaign.EXIT_PENDING
    assert len(child_case_ids) == 1

    monkeypatch.setattr(
        campaign,
        "_require_heavy_windows_path_budget",
        path_budget,
    )
    resume = replace(options, resume=True, verify_only=False)
    assert campaign.run_campaign(resume) == campaign.EXIT_PASS
    assert child_case_ids[-1] == (units[1].unit_id,)
    assert len(list_campaign_attempts(options.campaign_root)) == 2


def test_heavy_resume_retries_in_original_suite_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2), _unit(3))
    effective = {
        "candidate": {
            "tree_sha256": stable_tree_sha256(options.skill_source),
            "excluded_names": [],
        },
        "codex": {"windows_powershell_core_host": None},
        "synthetic": True,
    }
    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", options.campaign_root.parent)
    monkeypatch.setattr(campaign, "load_heavy_v3_campaign_units", lambda _options: units)
    monkeypatch.setattr(
        campaign,
        "build_heavy_v3_effective_config",
        lambda *_args, **_kwargs: effective,
    )
    monkeypatch.setattr(
        campaign,
        "assert_heavy_v3_effective_inputs_frozen",
        lambda *_args, **_kwargs: None,
    )
    child_case_ids: list[tuple[str, ...]] = []

    def child(argv: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        del cwd
        case_ids = tuple(
            argv[index + 1]
            for index, value in enumerate(argv)
            if value == "--case-id"
        )
        child_case_ids.append(case_ids)
        return subprocess.CompletedProcess(list(argv), 1, "synthetic\n", "")

    validations = iter(
        (
            _validation(
                (units[0],),
                statuses=("RETRYABLE",),
                pending=(units[1].unit_id, units[2].unit_id),
                retry_categories=("quota_or_rate_limit",),
            ),
            _validation(units, statuses=("PASS", "PASS", "PASS")),
        )
    )
    monkeypatch.setattr(campaign, "run_child", child)
    monkeypatch.setattr(
        campaign,
        "validate_heavy_v3_child_run",
        lambda *_args, **_kwargs: next(validations),
    )

    assert campaign.run_campaign(options) == campaign.EXIT_PENDING
    resume = replace(options, resume=True, verify_only=False)
    assert campaign.run_campaign(resume) == campaign.EXIT_PASS
    expected_order = tuple(unit.unit_id for unit in units)
    assert child_case_ids == [expected_order, expected_order]
    assert len(list_campaign_attempts(options.campaign_root)) == 2


def test_heavy_campaign_attributes_later_evidence_error_to_that_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    units = (_unit(1), _unit(2), _unit(3))
    effective = {
        "candidate": {
            "tree_sha256": stable_tree_sha256(options.skill_source),
            "excluded_names": [],
        },
        "codex": {"windows_powershell_core_host": None},
        "synthetic": True,
    }
    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", options.campaign_root.parent)
    monkeypatch.setattr(campaign, "load_heavy_v3_campaign_units", lambda _options: units)
    monkeypatch.setattr(
        campaign,
        "build_heavy_v3_effective_config",
        lambda *_args, **_kwargs: effective,
    )
    monkeypatch.setattr(
        campaign,
        "assert_heavy_v3_effective_inputs_frozen",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        campaign,
        "run_child",
        lambda argv, *, cwd: subprocess.CompletedProcess(list(argv), 1, "", ""),
    )

    def fail_later_unit(*_args: Any, **_kwargs: Any) -> ChildValidation:
        raise campaign._HeavyV3UnitEvidenceError(
            units[1].unit_id,
            "later scenario evidence is inconsistent",
        )

    monkeypatch.setattr(
        campaign,
        "validate_heavy_v3_child_run",
        fail_later_unit,
    )

    assert campaign.run_campaign(options) == campaign.EXIT_BLOCKED
    consolidated = json.loads(
        (options.campaign_root / campaign.CONSOLIDATED_SUMMARY_FILE).read_text(
            encoding="utf-8"
        )
    )
    assert consolidated["blocked_unit_ids"] == [units[1].unit_id]
    assert consolidated["pending_unit_ids"] == [
        units[0].unit_id,
        units[2].unit_id,
    ]


def test_campaign_typed_import_plan_and_archived_oracle_join(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_import_business_plan_v3 import (
        compile_import_business_plan,
    )
    from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
    from tests.semantic.support.codex_import_assets_v3 import materialize_import_case
    from tests.semantic.support.codex_import_runtime_v3 import build_import_runtime_plan
    from tests.semantic.test_codex_import_business_plan_v3 import (
        _after_value,
        _snapshot,
        _verification,
    )

    scenario = load_eval_bundle_v3(
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "evals"
        / "suite-v3.json"
    ).scenario("O22-AUDIO-IMPORT-01")
    scenario_root = tmp_path / "import-provenance"
    asset_root = scenario_root / "owned" / "assets" / "import-case"
    project = scenario_root / "owned" / "project" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    materialized = materialize_import_case(
        scenario,
        version="2022.1",
        asset_root=asset_root,
    )
    plan = build_import_runtime_plan(
        scenario,
        materialized,
        sandbox_project=project,
    )
    before = _snapshot(plan, before=True)
    protocol = build_audio_import_composer_protocol(plan.operation_requests[0])
    sections = compile_import_business_plan(
        scenario,
        materialized,
        plan,
        before,
        protocol,
    )
    provenance = _direct_typed_provenance(
        scenario,
        version="2022.1",
        scenario_root=scenario_root,
        protocol=protocol,
        visible_values=materialized.visible_values,
    )
    expected_unit = SimpleNamespace(
        scenario=scenario,
        unit_id=scenario.id,
        version="2022.1",
    )
    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=expected_unit,
        provenance=provenance,
    )
    assert parsed is not None
    campaign._validate_heavy_v3_typed_archived_verification(
        parsed,
        _verification(sections, after=_after_value(plan)),
        api=scenario.api,
        primary_count=scenario.primary_dispatch.count,
        task_root=tmp_path,
        label="synthetic import oracle",
    )


def test_campaign_typed_compound_import_plan_accepts_canonical_archive_order(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_eval_protocol_v3 import (
        build_metadata_transaction_protocol,
    )
    from tests.semantic.support.codex_gateway_broker import (
        project_required_metadata_tokens,
    )
    from tests.semantic.support.codex_import_assets_v3 import (
        bound_import_metadata_tokens,
    )
    from tests.semantic.support.codex_import_business_plan_v3 import (
        compile_import_business_plan,
    )
    from tests.semantic.test_codex_import_runtime_v3 import (
        _compound_prepared,
        _sound_discovery,
    )

    unit, materialized, _backend, _fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP25-O22-AUDIO-IMPORT-02",
    )
    tokens = bound_import_metadata_tokens(materialized)
    projection = project_required_metadata_tokens(
        _sound_discovery(),
        object_type="Sound",
        required_tokens=tokens,
    )
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence="audio_import_v1",
    )
    before = runtime.hidden_before
    assert before is not None
    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )
    archived = json.loads(
        json.dumps(
            sections.writer_kwargs(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    )
    selected_names = [
        row["name"]
        for row in archived["static_expectation"]["metadata_binding"][
            "selected"
        ].values()
    ]
    assert selected_names[:3] != list(tokens[:3])

    parsed = campaign._validate_heavy_v3_typed_business_plan(
        archived,
        expected_unit=unit,
        provenance=SimpleNamespace(protocol=protocol),
    )
    assert parsed is not None
    assert parsed.static_expectation["dynamic_tokens"] == list(tokens)


@pytest.mark.parametrize(
    "unit_id",
    [
        "CMP22-O22-AUDIO-IMPORT-03",
        "CMP25-O22-AUDIO-IMPORT-03",
    ],
)
def test_campaign_compound_import_oracle_projects_only_after_typed_validation(
    tmp_path: Path,
    unit_id: str,
) -> None:
    from tests.semantic.support.codex_eval_protocol_v3 import (
        build_metadata_transaction_protocol,
    )
    from tests.semantic.support.codex_gateway_broker import (
        project_required_metadata_tokens,
    )
    from tests.semantic.support.codex_import_assets_v3 import (
        bound_import_metadata_tokens,
    )
    from tests.semantic.support.codex_import_business_plan_v3 import (
        compile_import_business_plan,
    )
    from tests.semantic.test_codex_import_runtime_v3 import (
        _compound_prepared,
        _sound_discovery,
    )

    unit, materialized, backend, _fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id=unit_id,
    )
    tokens = bound_import_metadata_tokens(materialized)
    projection = project_required_metadata_tokens(
        _sound_discovery(),
        object_type="Sound",
        required_tokens=tokens,
    )
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence="audio_import_v1",
    )
    before = runtime.hidden_before
    assert before is not None
    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )
    backend.apply_case(unit.scenario, runtime.plan)
    verification = json.loads(
        json.dumps(
            asdict(runtime.verify_after_execution()),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    plan_sha256 = "a" * 64
    prompt_evidence = SimpleNamespace(
        business_oracle_plan=SimpleNamespace(sha256=plan_sha256),
        typed_sections=sections,
        protocol=protocol,
    )
    envelope = {
        "contract": campaign.HEAVY_V3_ORACLE_CONTRACT,
        "scenario_id": unit.scenario.id,
        "version": unit.version,
        "api": unit.scenario.api,
        "runner": "project",
        "business_oracle_plan_sha256": plan_sha256,
        "verification": verification,
    }

    campaign._validate_heavy_v3_archived_verification(
        envelope,
        api=unit.scenario.api,
        scenario_id=unit.scenario.id,
        version=unit.version,
        runner="project",
        primary_count=1,
        task_root=tmp_path,
        prompt_evidence=prompt_evidence,
        scenario_fixture=unit.scenario.fixture,
        label="synthetic compound import oracle",
    )

    tampered = copy.deepcopy(envelope)
    tampered["verification"]["after"]["rows"][0]["properties"][0][
        "value"
    ] = "__tampered__"
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="typed plan/evidence binding is invalid",
    ):
        campaign._validate_heavy_v3_archived_verification(
            tampered,
            api=unit.scenario.api,
            scenario_id=unit.scenario.id,
            version=unit.version,
            runner="project",
            primary_count=1,
            task_root=tmp_path,
            prompt_evidence=prompt_evidence,
            scenario_fixture=unit.scenario.fixture,
            label="synthetic compound import oracle",
        )


def test_campaign_typed_compound_object_plan_binds_2025_recipe_lane() -> None:
    from tests.semantic.support.codex_compound_heavy_v1 import (
        load_compound_heavy_profile,
    )
    from tests.semantic.support.codex_object_business_plan_v3 import (
        ObjectBusinessPlanError,
        build_object_merge_query_protocol,
    )

    profile = load_compound_heavy_profile(
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in profile.units
        if row.unit_id == "CMP25-OBJ22-F-CREATE-02"
    )
    recipe = build_object_heavy_v3_recipe(
        unit.base_scenario_id,
        version=unit.version,
    )
    protocol = build_object_merge_query_protocol(unit.scenario, recipe)
    assert protocol is not None
    sections = compile_object_business_plan(
        unit.scenario,
        recipe,
        protocol,
        _synthetic_object_before(recipe),
        (),
    )

    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=unit,
        provenance=SimpleNamespace(protocol=protocol),
    )

    assert parsed is not None
    assert parsed.static_expectation["version"] == "2025.1"
    assert (
        parsed.static_expectation["request"]["value"]["arguments"]["parent"]["value"]
        == r"\Containers\Default Work Unit\SemanticLab\NPC"
    )

    with pytest.raises(
        ObjectBusinessPlanError,
        match="scenario and reviewed recipe are misbound",
    ):
        campaign._validate_heavy_v3_typed_business_plan(
            sections.writer_kwargs(),
            expected_unit=replace(unit, version="2022.1"),
            provenance=SimpleNamespace(protocol=protocol),
        )


def test_campaign_object_recipe_fixture_fallback_binds_2025_lane() -> None:
    from tests.semantic.support.codex_compound_heavy_v1 import (
        load_compound_heavy_profile,
    )

    profile = load_compound_heavy_profile(
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in profile.units
        if row.unit_id == "CMP25-OBJ22-F-CREATE-02"
    )
    recipe = build_object_heavy_v3_recipe(
        unit.base_scenario_id,
        version=unit.version,
    )
    expected = {
        "kind": "object_recipe",
        "sha256": campaign._canonical_sha256(
            campaign._heavy_v3_plan_json_value(recipe)
        ),
    }
    fallback_unit = SimpleNamespace(
        scenario=SimpleNamespace(api="ak.wwise.core.unknown"),
        base_scenario_id=unit.base_scenario_id,
        version=unit.version,
    )

    assert campaign._heavy_v3_business_plan_fixture_spec(
        {"fixture_spec": expected},
        expected_unit=fallback_unit,
    ) == expected

    stale_2022 = build_object_heavy_v3_recipe(unit.base_scenario_id)
    stale_digest = campaign._canonical_sha256(
        campaign._heavy_v3_plan_json_value(stale_2022)
    )
    assert expected["sha256"] != stale_digest
    assert campaign._heavy_v3_business_plan_fixture_spec(
        {
            "fixture_spec": {
                "kind": "object_recipe",
                "sha256": stale_digest,
            }
        },
        expected_unit=fallback_unit,
    ) == expected


@pytest.mark.parametrize(
    ("api", "schema_version", "fixture_kind"),
    (
        (
            "ak.wwise.core.audio.import",
            "waapi-skill.import-business-plan/v1",
            "import_materialized_runtime_v1",
        ),
        (
            "ak.wwise.core.audio.import",
            "waapi-skill.import-business-plan/v2",
            "import_compound_materialized_runtime_v2",
        ),
        (
            "ak.wwise.core.audio.importTabDelimited",
            "waapi-skill.import-business-plan/v2",
            "import_compound_materialized_runtime_v2",
        ),
    ),
)
def test_campaign_import_fixture_spec_accepts_only_schema_bound_kinds(
    api: str,
    schema_version: str,
    fixture_kind: str,
) -> None:
    digest = "a" * 64
    unit = _Unit(
        unit_id="O22-IMPORT-FIXTURE-SPEC",
        version="2022.1",
        scenario=_Scenario(
            "O22-IMPORT-FIXTURE-SPEC",
            api,
            "synthetic natural import request",
        ),
    )
    assert campaign._heavy_v3_business_plan_fixture_spec(
        {
            "fixture_spec": {
                "kind": fixture_kind,
                "sha256": digest,
            },
            "static_expectation": {
                "family_schema_version": schema_version,
            },
        },
        expected_unit=unit,
    ) == {
        "kind": fixture_kind,
        "sha256": digest,
    }


@pytest.mark.parametrize(
    ("schema_version", "fixture_kind"),
    (
        (
            "waapi-skill.import-business-plan/v2",
            "import_materialized_runtime_v1",
        ),
        (
            "waapi-skill.import-business-plan/v2",
            "import_compound_materialized_runtime_v3",
        ),
        (
            "waapi-skill.import-business-plan/v3",
            "import_compound_materialized_runtime_v2",
        ),
    ),
)
def test_campaign_import_fixture_spec_rejects_mismatched_or_unknown_kind(
    schema_version: str,
    fixture_kind: str,
) -> None:
    unit = _Unit(
        unit_id="O22-IMPORT-FIXTURE-SPEC",
        version="2022.1",
        scenario=_Scenario(
            "O22-IMPORT-FIXTURE-SPEC",
            "ak.wwise.core.audio.import",
            "synthetic natural import request",
        ),
    )
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="typed (?:import )?business-oracle fixture identity is invalid",
    ):
        campaign._heavy_v3_business_plan_fixture_spec(
            {
                "fixture_spec": {
                    "kind": fixture_kind,
                    "sha256": "a" * 64,
                },
                "static_expectation": {
                    "family_schema_version": schema_version,
                },
            },
            expected_unit=unit,
        )


def test_campaign_import_snapshot_rejects_legacy_and_escaping_relative_evidence(
    tmp_path: Path,
) -> None:
    from tests.semantic.test_codex_import_business_plan_v3 import (
        _after_value,
        _case,
    )

    scenario, _materialized, plan, _before, _protocol = _case(
        tmp_path,
        "O22-AUDIO-IMPORT-01",
    )
    snapshot = _after_value(plan)
    campaign._validate_import_snapshot(
        snapshot,
        scenario_id=scenario.id,
        label="synthetic import snapshot",
    )

    escaped = copy.deepcopy(snapshot)
    escaped_source = next(
        row["object"]["audio_source"]
        for row in escaped["rows"]
        if isinstance(row.get("object"), dict)
    )
    escaped_source["original_relative_path"] = "../escape.wav"
    with pytest.raises(campaign.CampaignEvidenceError, match="canonical"):
        campaign._validate_import_snapshot(
            escaped,
            scenario_id=scenario.id,
            label="escaping import snapshot",
        )

    legacy = copy.deepcopy(snapshot)
    legacy_source = next(
        row["object"]["audio_source"]
        for row in legacy["rows"]
        if isinstance(row.get("object"), dict)
    )
    legacy_source["originalRelativeFilePath"] = legacy_source[
        "original_relative_path"
    ]
    with pytest.raises(campaign.CampaignEvidenceError, match="audio source"):
        campaign._validate_import_snapshot(
            legacy,
            scenario_id=scenario.id,
            label="legacy import snapshot",
        )


def test_campaign_archive_path_validators_are_host_flavor_aware() -> None:
    windows_proof = {
        "path": r"C:\Campaign\ORIGINALS\SFX\THUNDER.WAV",
        "relative_path": "Originals/SFX/Thunder.wav",
        "size": 16,
        "sha256": "a" * 64,
    }
    campaign._validate_integration_v2_file_proof(
        windows_proof,
        label="Windows integration proof",
        allow_null_relative=False,
    )
    campaign._validate_import_original_path_binding(
        windows_proof,
        original_relative_path="SFX/Thunder.wav",
        originals_files=[windows_proof],
        label="Windows import proof",
    )

    posix_case_drift = {
        **windows_proof,
        "path": "/campaign/Originals/SFX/THUNDER.WAV",
    }
    with pytest.raises(CampaignEvidenceError, match="inconsistent"):
        campaign._validate_import_original_path_binding(
            posix_case_drift,
            original_relative_path="SFX/Thunder.wav",
            originals_files=[posix_case_drift],
            label="POSIX import proof",
        )

    with pytest.raises(CampaignEvidenceError, match="absolute host path"):
        campaign._validate_integration_v2_file_proof(
            {**windows_proof, "path": "relative/Thunder.wav"},
            label="relative integration proof",
            allow_null_relative=False,
        )


def test_campaign_real_directory_and_text_guards_reject_reparse_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    text_path = child / "evidence.txt"
    text_path.write_bytes("证据\n".encode("utf-8"))
    text_path.chmod(0o600)
    empty_path = child / "empty.txt"
    empty_path.write_bytes(b"")
    empty_path.chmod(0o600)

    assert campaign._require_real_directory(
        root,
        label="test root",
    ) == root.resolve(strict=True)
    assert campaign._strict_real_subdirectory_names(root) == {"child"}
    assert campaign._load_strict_regular_text(text_path) == "证据\n"
    assert campaign._load_strict_regular_text(empty_path) == ""

    real_guard = campaign.path_is_link_or_reparse

    def reports_child_reparse(
        path: Path,
        *,
        metadata: Any | None = None,
    ) -> bool:
        return Path(path) == child or real_guard(Path(path), metadata=metadata)

    monkeypatch.setattr(campaign, "path_is_link_or_reparse", reports_child_reparse)
    with pytest.raises(CampaignEvidenceError, match="non-directory entry"):
        campaign._strict_real_subdirectory_names(root)
    with pytest.raises(CampaignEvidenceError, match="not a real directory"):
        campaign._require_real_directory(child, label="reparse child")


def test_campaign_scenario_directory_scan_rejects_reparse_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix_root = tmp_path / "matrix"
    scenario = matrix_root / "scenarios" / "001-case"
    scenario.mkdir(parents=True)
    real_guard = campaign.path_is_link_or_reparse

    def reports_scenario_reparse(
        path: Path,
        *,
        metadata: Any | None = None,
    ) -> bool:
        return Path(path) == scenario or real_guard(Path(path), metadata=metadata)

    monkeypatch.setattr(
        campaign,
        "path_is_link_or_reparse",
        reports_scenario_reparse,
    )
    with pytest.raises(CampaignEvidenceError, match="not a real directory"):
        campaign._heavy_v3_scenario_directories(matrix_root)


def test_prepare_campaign_root_checks_lexical_reparse_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    campaign_root = workspace / "campaign-a"
    campaign_root.mkdir(parents=True)
    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", workspace)
    real_guard = campaign.path_is_link_or_reparse

    def reports_campaign_reparse(
        path: Path,
        *,
        metadata: Any | None = None,
    ) -> bool:
        return Path(path) == campaign_root or real_guard(Path(path), metadata=metadata)

    monkeypatch.setattr(
        campaign,
        "path_is_link_or_reparse",
        reports_campaign_reparse,
    )
    with pytest.raises(campaign.CampaignConfigError, match="real directory"):
        campaign.prepare_campaign_root(
            SimpleNamespace(campaign_root=campaign_root, resume=True)
        )


def test_campaign_typed_media_plan_and_archived_oracle_join(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_audio_media_business_plan_v3 import (
        _expected_media_protocol,
        compile_media_pool_business_plan,
    )
    from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
    from tests.semantic.test_codex_audio_media_business_plan_v3 import _media_case

    scenario = load_eval_bundle_v3(
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "evals"
        / "suite-v3.json"
    ).scenario("VS25-F-MEDIAPOOL-GET-01")
    media_root = tmp_path / "media-case"
    media_root.mkdir()
    case, staged, oracle = _media_case(1, media_root)
    protocol = _expected_media_protocol(case, oracle)
    project_digest = "a" * 64
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest=project_digest,
        reviewed_scenario_fixture=scenario.fixture,
    )
    provenance = _direct_typed_provenance(
        scenario,
        version="2025.1",
        scenario_root=tmp_path / "media-provenance",
        protocol=protocol,
        visible_values={},
    )
    expected_unit = SimpleNamespace(
        scenario=scenario,
        unit_id=scenario.id,
        version="2025.1",
    )
    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=expected_unit,
        provenance=provenance,
    )
    assert parsed is not None
    campaign._validate_heavy_v3_typed_archived_verification(
        parsed,
        {
                "sealed_oracle": {
                    "rows": sections.live_binding["sealed_rows"],
                    "request": sections.live_binding["request"],
                    "candidate_keys": sections.live_binding["candidate_keys"],
                    "expected_keys": sections.live_binding["expected_keys"],
                },
            "project_digest_before": project_digest,
            "project_digest_after": project_digest,
            "source_fingerprint_after": sections.live_binding[
                "source_fingerprint"
            ],
        },
        api=scenario.api,
        primary_count=scenario.primary_dispatch.count,
        task_root=tmp_path,
        label="synthetic Media Pool oracle",
    )
    campaign._validate_media_final_response(
        "all\nmedia-1",
        oracle={
            "scenario_id": oracle.scenario_id,
            "rows": sections.live_binding["sealed_rows"],
            "expected_keys": list(oracle.expected_keys),
            "semantic_answer": sections.live_binding["semantic_answer"],
            "request": sections.live_binding["request"],
        },
        label="synthetic Media Pool final response",
    )


def test_campaign_extracts_exact_media_pool_post_filter_protocol(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_audio_media_business_plan_v3 import (
        _expected_media_protocol,
    )
    from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
    from tests.semantic.test_codex_media_pool_runtime_v3 import _sealed_case01

    scenario = load_eval_bundle_v3(
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "evals"
        / "suite-v3.json"
    ).scenario("VS25-F-MEDIAPOOL-GET-01")
    _runtime, staged, oracle = _sealed_case01(tmp_path / "sealed")
    protocol = _expected_media_protocol(staged.materialized, oracle)
    provenance = _direct_typed_provenance(
        scenario,
        version="2025.1",
        scenario_root=tmp_path / "provenance",
        protocol=protocol,
        visible_values={},
    )
    evidence = SimpleNamespace(provenance=provenance)

    assert campaign._heavy_v3_protocol_call_request(
        evidence,
        api="ak.wwise.core.mediaPool.get",
    ) == {
        "args": campaign._heavy_v3_plan_json_value(oracle.request.args),
        "options": campaign._heavy_v3_plan_json_value(oracle.request.options),
        "post_filter": {
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": "footstep",
            "limit": 20,
        },
    }

    steps = list(protocol.steps)
    media_index = next(
        index
        for index, step in enumerate(steps)
        if step.subcommand == "draft-check"
    )
    media_step = steps[media_index]
    tampered_arguments = list(media_step.arguments)
    tampered_arguments[-2] = "--different-post-filter-flag"
    steps[media_index] = replace(media_step, arguments=tuple(tampered_arguments))
    with pytest.raises(ValueError, match="closed Media Pool result filter"):
        replace(protocol, steps=tuple(steps))

    archived = campaign._heavy_v3_plan_json_value(oracle)
    campaign._validate_media_pool_sealed_oracle(
        archived,
        scenario_id=scenario.id,
        label="post-filter oracle",
    )
    missing = copy.deepcopy(archived)
    missing["request"]["post_filter"] = None
    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_media_pool_sealed_oracle(
            missing,
            scenario_id=scenario.id,
            label="missing post-filter oracle",
        )
    changed = copy.deepcopy(archived)
    changed["request"]["post_filter"]["value"] = "Footstep"
    with pytest.raises(campaign.CampaignEvidenceError, match="post filter is malformed"):
        campaign._validate_media_pool_sealed_oracle(
            changed,
            scenario_id=scenario.id,
            label="changed post-filter oracle",
        )
    extra = copy.deepcopy(archived)
    extra["request"]["post_filter"]["extra"] = True
    with pytest.raises(campaign.CampaignEvidenceError, match="schema is not closed"):
        campaign._validate_media_pool_sealed_oracle(
            extra,
            scenario_id=scenario.id,
            label="extra post-filter oracle",
        )


def test_campaign_import_refusal_uses_authenticated_broker_error(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_import_business_plan_v3 import (
        compile_import_business_plan,
    )
    from tests.semantic.test_codex_import_business_plan_v3 import (
        _case,
        _verification,
    )

    scenario, materialized, plan, before, protocol = _case(
        tmp_path / "refusal-case",
        "O22-AUDIO-TAB-01",
    )
    sections = compile_import_business_plan(
        scenario,
        materialized,
        plan,
        before,
        protocol,
    )
    task_root = tmp_path / "task"
    task_root.mkdir()

    def write_refusal(error_code: str) -> None:
        matrix.write_json(
            task_root / "task-result.json",
            {
                "broker": {
                    "records": [
                        {
                            "step_name": "tx01.preview",
                            "authenticated": True,
                            "accepted": True,
                            "succeeded": True,
                            "runner_exit_code": 2,
                            "payload": {
                                "contract": "waapi-skill.gateway-result/v1",
                                "ok": False,
                                "command": "preview",
                                "error_code": error_code,
                            },
                        }
                    ]
                }
            },
        )

    verification = _verification(
        sections,
        after=sections.live_binding["before_snapshot"],
        phase="zero_dispatch",
    )
    write_refusal("INPUT_FILE_NOT_FOUND")
    campaign._validate_heavy_v3_typed_archived_verification(
        sections,
        verification,
        api=scenario.api,
        primary_count=0,
        task_root=task_root,
        label="synthetic import refusal",
    )
    write_refusal("WRONG_ERROR")
    with pytest.raises(CampaignEvidenceError, match="refusal error"):
        campaign._validate_heavy_v3_typed_archived_verification(
            sections,
            verification,
            api=scenario.api,
            primary_count=0,
            task_root=task_root,
            label="synthetic import refusal",
        )


@pytest.mark.parametrize(
    ("scenario_id", "api", "primary_count", "fixture_kind"),
    (
        (
            "O22-SB-CONVERT-EXT-01",
            "ak.wwise.core.soundbank.convertExternalSources",
            1,
            "soundbank_function_materialized_v1",
        ),
        (
            "O22-SB-GENERATED-04",
            SOUNDBANK_TOPIC,
            4,
            "soundbank_topic_materialized_v1",
        ),
        (
            "O22-SB-PROCESS-DEF-05",
            "ak.wwise.core.soundbank.processDefinitionFiles",
            0,
            "soundbank_refusal_materialized_v1",
        ),
    ),
)
def test_campaign_typed_soundbank_function_topic_and_refusal_join(
    tmp_path: Path,
    scenario_id: str,
    api: str,
    primary_count: int,
    fixture_kind: str,
) -> None:
    unit = _soundbank_unit(
        scenario_id,
        api,
        primary_count=primary_count,
    )
    scenario_root = tmp_path / scenario_id
    (scenario_root / "owned").mkdir(parents=True)
    protocol, sections = _synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    provenance = _direct_typed_provenance(
        unit.scenario,
        version=unit.version,
        scenario_root=scenario_root,
        protocol=protocol,
        visible_values={},
    )
    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=unit,
        provenance=provenance,
    )
    assert parsed.fixture_spec["kind"] == fixture_kind
    if api == SOUNDBANK_TOPIC:
        assert parsed.payload_bindings["primary_steps"] == [
            "soundbank.generated.wait"
        ]
        assert len(parsed.live_binding["topic"]["expected_events"]) == primary_count
    task_root = tmp_path / f"task-{scenario_id}"
    task_root.mkdir()
    if primary_count == 0:
        matrix.write_json(
            task_root / "task-result.json",
            {
                "broker": {
                    "records": [
                        {
                            "step_name": "tx01.preview",
                            "authenticated": True,
                            "accepted": True,
                            "succeeded": True,
                            "runner_exit_code": 2,
                            "payload": {
                                "contract": "waapi-skill.gateway-result/v1",
                                "ok": False,
                                "command": "preview",
                                "error_code": PROCESS_REFUSAL_ERROR_CODE,
                            },
                        }
                    ]
                }
            },
        )
    verification = _synthetic_soundbank_verification(parsed)
    if api == SOUNDBANK_TOPIC:
        reordered = copy.deepcopy(verification)
        reordered["topic"]["observed_keys"] = list(
            reversed(reordered["topic"]["observed_keys"])
        )
        campaign._validate_heavy_v3_soundbank_topic_oracle(
            reordered,
            scenario_id=scenario_id,
            label="synthetic reordered topic oracle",
        )
        duplicate = copy.deepcopy(reordered)
        duplicate_keys = duplicate["topic"]["observed_keys"]
        duplicate_keys[-1] = duplicate_keys[0]
        with pytest.raises(CampaignEvidenceError, match="topic identities"):
            campaign._validate_heavy_v3_soundbank_topic_oracle(
                duplicate,
                scenario_id=scenario_id,
                label="synthetic duplicate topic oracle",
            )
    campaign._validate_heavy_v3_typed_archived_verification(
        parsed,
        verification,
        api=api,
        primary_count=primary_count,
        task_root=task_root,
        label="synthetic SoundBank oracle",
    )


def test_campaign_soundbank_refusal_requires_authenticated_broker_error(
    tmp_path: Path,
) -> None:
    unit = _soundbank_unit(
        "O22-SB-PROCESS-DEF-05",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        primary_count=0,
    )
    scenario_root = tmp_path / "soundbank-refusal"
    (scenario_root / "owned").mkdir(parents=True)
    _protocol, sections = _synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    task_root = tmp_path / "soundbank-refusal-task"
    task_root.mkdir()
    matrix.write_json(
        task_root / "task-result.json",
        {
            "broker": {
                "records": [
                    {
                        "step_name": "tx01.preview",
                        "authenticated": True,
                        "accepted": True,
                        "succeeded": True,
                        "runner_exit_code": 2,
                        "payload": {
                            "contract": "waapi-skill.gateway-result/v1",
                            "ok": False,
                            "command": "preview",
                            "error_code": "WRONG_ERROR",
                        },
                    }
                ]
            }
        },
    )
    with pytest.raises(CampaignEvidenceError, match="SoundBank refusal"):
        campaign._validate_heavy_v3_typed_archived_verification(
            sections,
            _synthetic_soundbank_verification(sections),
            api=unit.scenario.api,
            primary_count=0,
            task_root=task_root,
            label="synthetic SoundBank refusal",
        )


@pytest.mark.parametrize(
    ("api", "attack"),
    (
        ("ak.wwise.cli.convertExternalSource", "output"),
        ("ak.wwise.cli.tabDelimitedImport", "guid"),
        ("ak.wwise.cli.migrate", "version"),
    ),
)
def test_campaign_typed_cli_terminal_output_guid_and_version_binding(
    tmp_path: Path,
    api: str,
    attack: str,
) -> None:
    unit = _cli_api_unit(
        api,
        5 if api == "ak.wwise.cli.tabDelimitedImport" else 1,
    )
    scenario_root = tmp_path / attack
    (scenario_root / "owned").mkdir(parents=True)
    protocol, sections = _synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    provenance = _direct_typed_provenance(
        unit.scenario,
        version=unit.version,
        scenario_root=scenario_root,
        protocol=protocol,
        visible_values={},
    )
    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=unit,
        provenance=provenance,
    )
    assert parsed.fixture_spec["kind"] == "cli_prepared_runtime_v1"
    if api == "ak.wwise.cli.migrate":
        execute = next(step for step in protocol.steps if step.name == "tx01.execute")
        assert execute.terminal_execute is True
        assert execute.allowed_exit_codes == (0, 2)
        assert all(step.name != "tx01.verify" for step in protocol.steps)
    verification = _synthetic_cli_verification(parsed)
    campaign._validate_heavy_v3_typed_archived_verification(
        parsed,
        verification,
        api=api,
        primary_count=1,
        task_root=tmp_path,
        label="synthetic CLI oracle",
    )
    tampered = json.loads(json.dumps(verification))
    if attack == "output":
        expected_path = parsed.static_expectation["expected_outputs"][0]["path"]
        files = tampered["after"]["output_tree"]["files"]
        tampered["after"]["output_tree"]["files"] = [
            row for row in files if row["path"] != expected_path
        ]
        tampered["after"]["output_tree"]["sha256"] = (
            _synthetic_cli_tree_sha256(
                tampered["after"]["output_tree"]["files"]
            )
        )
    elif attack == "guid":
        target_path = parsed.static_expectation["asset_spec"]["expected"][
            "objects"
        ][0]["path"]
        target = next(
            row
            for row in tampered["after"]["objects"]
            if row["path"] == target_path
        )
        target["object_id"] = "not-a-guid"
    else:
        tampered["after"]["project_version"] = "v2021.1.0"
    with pytest.raises(CampaignEvidenceError, match="typed plan/evidence"):
        campaign._validate_heavy_v3_typed_archived_verification(
            parsed,
            tampered,
            api=api,
            primary_count=1,
            task_root=tmp_path,
            label="synthetic CLI oracle",
        )


def test_campaign_cli_oracle_allows_generated_soundbank_project_caches(
    tmp_path: Path,
) -> None:
    scenario = next(
        item
        for item in _suite_cli_cases()
        if item.api == "ak.wwise.cli.generateSoundbank"
        and item.scenario_index == 2
    )
    runtime_root = tmp_path / "generate-cache" / "owned" / "cli-runtime"
    _plan, runtime, backend = _build_cli_runtime(scenario, runtime_root)
    _seal_cli_runtime(
        runtime,
        backend,
        _make_cli_console(runtime_root),
        31200,
    )
    sections = compile_cli_business_plan(runtime, runtime.gateway_protocol())
    verification = _synthetic_cli_verification(sections)
    after_files = verification["after"]["project_tree"]["files"]
    project_root = Path(verification["after"]["project_tree"]["root"])
    for relative_path, payload in (
        ("Originals/Voices/English(US)/generated.akd", b"analysis"),
        ("SampleProject.crossover.validationcache", b"validation"),
    ):
        after_files.append(
            {
                "path": str(project_root / relative_path),
                "relative_path": relative_path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mtime_ns": 1,
            }
        )
    after_files.sort(key=lambda row: str(row["relative_path"]))
    verification["after"]["project_tree"]["sha256"] = (
        _synthetic_cli_tree_sha256(after_files)
    )

    campaign._validate_heavy_v3_cli_oracle(
        verification,
        api=scenario.api,
        scenario_id=scenario.id,
        label="synthetic CLI oracle",
    )

    authored_change = json.loads(json.dumps(verification))
    authored_change["after"]["project_tree"] = _synthetic_cli_changed_tree(
        authored_change["after"]["project_tree"]
    )
    with pytest.raises(CampaignEvidenceError, match="output/project delta"):
        campaign._validate_heavy_v3_cli_oracle(
            authored_change,
            api=scenario.api,
            scenario_id=scenario.id,
            label="synthetic CLI oracle",
        )


@pytest.mark.parametrize(
    "attack",
    [None, "unbound_akd", "changed_wav", "extra_file", "bad_cache", "bad_settings"],
)
def test_campaign_cli_convert_oracle_uses_closed_archived_side_effect_relation(
    tmp_path: Path,
    attack: str | None,
) -> None:
    scenario = next(
        item for item in _suite_cli_cases()
        if item.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    runtime_root = tmp_path / "convert-side-effects" / "owned" / "cli-runtime"
    _plan, runtime, backend = _build_cli_runtime(scenario, runtime_root)
    _seal_cli_runtime(
        runtime,
        backend,
        _make_cli_console(runtime_root),
        31300,
    )
    sections = compile_cli_business_plan(runtime, runtime.gateway_protocol())
    verification = _synthetic_convert_verification_with_side_effects(sections)
    if attack is None:
        campaign._validate_heavy_v3_cli_oracle(
            verification,
            api=scenario.api,
            scenario_id=scenario.id,
            label="synthetic CLI oracle",
        )
        return

    before_assets = {
        row["relative_path"]: row
        for row in verification["before"]["asset_tree"]["files"]
    }
    asset_tree = verification["after"]["asset_tree"]
    project_tree = verification["after"]["project_tree"]
    if attack == "unbound_akd":
        row = next(
            row for row in asset_tree["files"]
            if row["relative_path"] not in before_assets
        )
        row["relative_path"] = "wav/unbound.akd"
        row["path"] = str(Path(asset_tree["root"]) / "wav/unbound.akd")
        asset_tree["files"].sort(key=lambda item: str(item["relative_path"]))
        asset_tree["sha256"] = _synthetic_cli_tree_sha256(asset_tree["files"])
    elif attack == "changed_wav":
        row = next(
            row for row in asset_tree["files"]
            if row["relative_path"].casefold().endswith(".wav")
        )
        row["sha256"] = "f" * 64 if row["sha256"] != "f" * 64 else "e" * 64
        asset_tree["sha256"] = _synthetic_cli_tree_sha256(asset_tree["files"])
    elif attack == "extra_file":
        _append_synthetic_cli_file(asset_tree, "wav/extra.tmp", b"extra")
    elif attack == "bad_cache":
        row = next(
            row for row in project_tree["files"]
            if row["relative_path"] == ".cache/CacheVersion"
        )
        row["sha256"] = hashlib.sha256(b"FAIL").hexdigest()
        project_tree["sha256"] = _synthetic_cli_tree_sha256(project_tree["files"])
    else:
        row = next(
            row for row in project_tree["files"]
            if row["relative_path"].endswith(".crossover.wsettings")
        )
        row["size"] = 0
        row["sha256"] = hashlib.sha256(b"").hexdigest()
        project_tree["sha256"] = _synthetic_cli_tree_sha256(project_tree["files"])

    with pytest.raises(CampaignEvidenceError, match="side effects"):
        campaign._validate_heavy_v3_cli_oracle(
            verification,
            api=scenario.api,
            scenario_id=scenario.id,
            label="synthetic CLI oracle",
        )


def test_cli_snapshot_accepts_xml_parent_without_name_or_id(tmp_path: Path) -> None:
    unit = _cli_api_unit("ak.wwise.cli.migrate", 1)
    scenario_root = tmp_path / "migration-parent"
    protocol, sections = _synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    del protocol
    snapshot = _synthetic_cli_verification(sections)["before"]
    snapshot["migration_inventory"] = [
        {
            "key": "Event|{2B98695B-2238-45B1-89C5-A5B826472425}",
            "identity": [
                "Event",
                "Play_Minigun",
                "{2B98695B-2238-45B1-89C5-A5B826472425}",
                ["ChildrenList", "", ""],
            ],
            "semantic_rows": [["Event", 0]],
            "reference_rows": [["Events/Minigun.wwu", "reference"]],
        }
    ]

    campaign._validate_cli_snapshot(snapshot, label="synthetic migration before")

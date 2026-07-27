from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_cli_runtime_v3 import (
    CLI_APIS,
    MAX_LOG_BYTES,
    CliEventRecord,
    CliObjectRecord,
    PreparedCliRuntime,
    ProcessPhaseEvidence,
    ProcessPhaseSpec,
)
from tests.semantic.support.codex_cli_business_plan_v3 import (
    parse_cli_business_plan_sections,
)
from tests.semantic.support.codex_eval_execution_v3 import build_heavy_units
from tests.semantic.support.codex_heavy_cli_case_runner_v3 import (
    HEAVY_CLI_RUN_CONTRACT,
    HEAVY_CLI_REVIEWED_CASE_APIS,
    HEAVY_CLI_RUNNER_APIS,
    CliPhaseResult,
    HeavyCliRunnerError,
    HeavyCliRunnerDependencies,
    HeavyCliRunnerOptions,
    _InfrastructureFailure,
    _SemanticFailure,
    _SealedCliBackend,
    _REVIEWED_CLI_SCENARIO_SHA256,
    _assert_tab_path_identity_closed,
    _classify_load_issues,
    _load_issue_lines,
    _reviewed_scenario_sha256,
    _validate_reviewed_cli_unit,
    _write_common_business_oracle_plan,
    run_heavy_cli_unit,
)
from tests.semantic.support.codex_harness import (
    CodexInfrastructureError,
    CodexInfrastructureFailure,
)
from tests.semantic.test_codex_cli_runtime_v3 import (
    FakeBackend,
    _apply_success,
    _suite_cli_cases,
)
from wwise_waapi.transactions import TransactionState, TransactionStore


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PROJECT = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
FAKE_GATEWAY_RUNNER = (
    REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "run.py"
).resolve()


def _fake_transaction_next_command(
    command: str,
    gateway_argv: tuple[str, ...],
    *,
    requires_explicit_user_confirmation: bool = False,
    requires_later_user_message: bool = False,
) -> dict[str, Any]:
    full_argv = (
        "python",
        str(FAKE_GATEWAY_RUNNER),
        "gateway.py",
        *gateway_argv,
    )
    result: dict[str, Any] = {
        "contract": "waapi-skill.gateway-next-command/v1",
        "command": command,
        "gateway_argv": list(gateway_argv),
        "full_argv": list(full_argv),
        "copy_exactly": True,
    }
    if requires_explicit_user_confirmation:
        result["requires_explicit_user_confirmation"] = True
    if requires_later_user_message:
        result["requires_later_user_message"] = True
    if os.name == "nt":
        result["shell_family"] = "windows-cmd"
        result["shell_command"] = subprocess.list2cmdline(full_argv)
    else:
        result["shell_family"] = "posix-sh"
        result["shell_command"] = shlex.join(full_argv)
    return result


@dataclass(slots=True)
class _FakeRecord:
    step_name: str
    payload: Mapping[str, Any]
    runner_exit_code: int
    succeeded: bool = True


@dataclass(slots=True)
class _FakeBackendSession:
    backend: FakeBackend
    call_count: int = 17
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class _FakeLock:
    def __init__(self, *, fail_release: bool = False) -> None:
        self.fail_release = fail_release
        self.entered = False
        self.exited = False

    def __enter__(self) -> "_FakeLock":
        self.entered = True
        return self

    def __exit__(self, *_args: Any) -> None:
        self.exited = True
        if self.fail_release:
            raise RuntimeError("synthetic lock release failure")


class _FakePhase:
    def __init__(
        self,
        spec: ProcessPhaseSpec,
        world: "_FakeWorld",
    ) -> None:
        self.spec = spec
        self.host = "127.0.0.1"
        self.port = int(spec.argv[spec.argv.index("--wamp-port") + 1])
        self._world = world
        self._started = False
        self._closed = False

    def start(self) -> None:
        assert not self._started and not self._closed
        self._started = True
        self._world.phase_events.append((self.spec.role, "start"))

    def close(self, *, expect_natural_exit: bool = False) -> CliPhaseResult:
        assert self._started and not self._closed
        self._closed = True
        self._world.phase_events.append((self.spec.role, "close"))
        if self.spec.role == "business":
            self._world.business_expected_natural_exit = expect_natural_exit
        residual = (
            (4242,)
            if self.spec.role == self._world.residual_role
            else ()
        )
        returncode = (
            self._world.business_returncode
            if self.spec.role == "business"
            else 0
        )
        return CliPhaseResult(
            evidence=ProcessPhaseEvidence(
                role=self.spec.role,
                argv=self.spec.argv,
                cwd=self.spec.cwd,
                shell=False,
                started=True,
                ready=True,
                process_exited=True,
                residual_pids=residual,
                open_project_path=self.spec.project_path,
                returncode=returncode,
                natural_exit_before_shutdown=(
                    self._world.natural_business_exit
                    if self.spec.role == "business"
                    else True
                ),
                runner_shutdown_requested=(
                    not self._world.natural_business_exit
                    if self.spec.role == "business"
                    else False
                ),
            ),
            stdout="",
            stderr="",
            log_overflow=False,
            ready_version="2022.1",
        )


class _FakeWorld:
    def __init__(
        self,
        *,
        source_project: Path,
        console_path: Path,
        duplicate_dispatch: bool = False,
        apply_business: bool = True,
        migration_indeterminate: bool = False,
        ordinary_indeterminate: bool = False,
        residual_role: str | None = None,
        mutate_source: bool = False,
        fail_lock_release: bool = False,
        delay_first_use_intro: bool = False,
        natural_business_exit: bool = False,
        dispatch_tamper: Mapping[str, Any] | None = None,
        extra_dispatch_api: str | None = None,
    ) -> None:
        self.source_project = source_project
        self.console_path = console_path
        self.duplicate_dispatch = duplicate_dispatch
        self.apply_business = apply_business
        self.migration_indeterminate = migration_indeterminate
        self.ordinary_indeterminate = ordinary_indeterminate
        self.residual_role = residual_role
        self.mutate_source = mutate_source
        self.fail_lock_release = fail_lock_release
        self.delay_first_use_intro = delay_first_use_intro
        self.natural_business_exit = natural_business_exit
        self.dispatch_tamper = dispatch_tamper
        self.extra_dispatch_api = extra_dispatch_api
        self.runtime: PreparedCliRuntime | None = None
        self.setup_backend: FakeBackend | None = None
        self.oracle_backend: FakeBackend | None = None
        self.phase_specs: list[ProcessPhaseSpec] = []
        self.phase_project_exists: list[tuple[str, bool]] = []
        self.phase_events: list[tuple[str, str]] = []
        self.backend_roles: list[str] = []
        self.business_expected_natural_exit = False
        self.business_returncode = 2 if migration_indeterminate else 0
        self.business_oracle_plans: list[Any] = []
        self.business_protocols: list[Any] = []
        self.executed_step_names: list[str] = []
        self.gateway_records: tuple[_FakeRecord, ...] = ()
        self.transaction_ids: dict[str, str] = {}
        self.materialize_project_languages: tuple[str | None, ...] = ()
        self.lock: _FakeLock | None = None
        self._next_port = 23100

    def environment_resolver(self, _env: Mapping[str, str]) -> Any:
        return SimpleNamespace(
            version="2022.1",
            console_path=self.console_path,
            sample_project_source=self.source_project,
        )

    def port_allocator(self, host: str) -> int:
        assert host == "127.0.0.1"
        self._next_port += 1
        return self._next_port

    def lock_factory(self, _root: Path) -> _FakeLock:
        self.lock = _FakeLock(fail_release=self.fail_lock_release)
        return self.lock

    def materialize_runtime(self, plan: Any) -> PreparedCliRuntime:
        from tests.semantic.support.codex_cli_runtime_v3 import materialize_cli_runtime

        if plan.project_path.is_file():
            document = ET.parse(plan.project_path).getroot()
            self.materialize_project_languages = tuple(
                row.get("Name")
                for row in document.findall(
                    "./ProjectInfo/Project/LanguageList/Language"
                )
            )
        self.runtime = materialize_cli_runtime(plan)
        return self.runtime

    def phase_factory(
        self,
        spec: ProcessPhaseSpec,
        _environment: Mapping[str, str],
    ) -> _FakePhase:
        self.phase_specs.append(spec)
        self.phase_project_exists.append(
            (spec.role, bool(spec.project_path and Path(spec.project_path).is_file()))
        )
        return _FakePhase(spec, self)

    def backend_factory(self, role: str, _host: str, _port: int) -> _FakeBackendSession:
        assert self.runtime is not None
        assert role in {"setup", "oracle"}
        self.backend_roles.append(role)
        if role == "setup":
            self.setup_backend = FakeBackend(self.runtime.plan.project_path)
            return _FakeBackendSession(self.setup_backend)
        backend = self.oracle_backend or self.setup_backend
        if backend is None:
            backend = FakeBackend(self.runtime.plan.project_path)
            self.oracle_backend = backend
        return _FakeBackendSession(backend)

    def task_runner(self, **kwargs: Any) -> Any:
        assert self.runtime is not None
        self.business_oracle_plans.append(kwargs["business_oracle_plan"])
        protocol = kwargs["protocol"]
        self.business_protocols.append(protocol)
        task_root = Path(kwargs["task_root"])
        task_root.mkdir(parents=True, exist_ok=False)
        evidence_directory = task_root / "broker" / "evidence"
        state_directory = task_root / "broker" / "state"
        evidence_directory.mkdir(parents=True)
        state_directory.mkdir(parents=True)

        records: list[_FakeRecord] = []
        turns: list[Any] = []
        previous_prefix = 0
        terminal_indeterminate = False
        for turn_index, prefix in enumerate(protocol.turn_prefix_counts, start=1):
            for step in protocol.steps[previous_prefix:prefix]:
                kwargs["trusted_step_pre_observer"](
                    step,
                    state_directory,
                    evidence_directory,
                )
                payload, exit_code = self._step_payload(
                    step,
                    state_directory=state_directory,
                )
                self.executed_step_names.append(step.name)
                if step.subcommand == "execute":
                    if self.apply_business and not self.ordinary_indeterminate:
                        self.oracle_backend = _apply_success(
                            self.runtime,
                            self.setup_backend,
                        )
                    if self.mutate_source:
                        self.source_project.write_text(
                            self.source_project.read_text(encoding="utf-8") + "\n<!-- drift -->\n",
                            encoding="utf-8",
                        )
                    if not self.ordinary_indeterminate:
                        self._write_dispatch(evidence_directory)
                record = _FakeRecord(
                    step_name=step.name,
                    payload=payload,
                    runner_exit_code=exit_code,
                )
                records.append(record)
                kwargs["trusted_step_observer"](
                    step,
                    payload,
                    state_directory,
                    evidence_directory,
                )
                if self.ordinary_indeterminate and step.subcommand == "execute":
                    terminal_indeterminate = True
                    break

            intro = (
                "已加载 waapi-skill。当前连接的 WAAPI 地址为 "
                f"{kwargs['runner_environment']['WWISE_WAAPI_HOST']}:"
                f"{kwargs['runner_environment']['WWISE_WAAPI_PORT']}，"
                "WAAPI 适配层版本为 2022.1，修改策略为 ask_before_changes。"
                "若有需要，可按需切换模式：read_only / ask_before_changes / allow_changes。"
            )
            response = "已按确认执行并完成检查。"
            agent_messages = (
                ("正在处理请求。", intro)
                if turn_index == 1 and self.delay_first_use_intro
                else (intro, response)
                if turn_index == 1
                else (response,)
            )
            gateway_command = f"validated-gateway-turn-{turn_index}"
            events = [
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "准备调用 gateway。"},
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": gateway_command,
                    },
                },
                *(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": message},
                    }
                    for message in agent_messages
                ),
            ]
            result = SimpleNamespace(
                final_response=agent_messages[-1],
                stdout="\n".join(json.dumps(event) for event in events),
                command_facts=SimpleNamespace(gateway_commands=(gateway_command,)),
            )
            turns.append(result)
            broker = SimpleNamespace(
                records=tuple(records),
                evidence_directory=str(evidence_directory),
                passed=(not terminal_indeterminate and prefix == len(protocol.steps)),
                terminal_indeterminate=terminal_indeterminate,
            )
            kwargs["turn_observer"](turn_index, result, broker)
            previous_prefix = len(records)
            if terminal_indeterminate:
                break

        broker = SimpleNamespace(
            records=tuple(records),
            evidence_directory=str(evidence_directory),
            passed=not terminal_indeterminate,
            terminal_indeterminate=terminal_indeterminate,
        )
        self.gateway_records = tuple(records)
        return SimpleNamespace(
            scenario_id=kwargs["scenario_id"],
            version=kwargs["version"],
            task_root=task_root,
            thread_id="fake-memory-isolated-thread",
            turns=tuple(turns),
            turn_grades=tuple(SimpleNamespace(passed=True) for _ in turns),
            broker_evidence=broker,
            passed=not terminal_indeterminate,
            terminal_indeterminate=terminal_indeterminate,
        )

    def _step_payload(
        self,
        step: Any,
        *,
        state_directory: Path,
    ) -> tuple[Mapping[str, Any], int]:
        store = TransactionStore(state_directory)
        transaction_label = step.name.rsplit(".", 1)[0]
        if step.subcommand == "preview":
            transaction_id = f"tx-cli-{len(self.transaction_ids) + 1:02d}"
            request = next(
                (
                    value.expected
                    for value in step.arguments
                    if hasattr(value, "expected")
                ),
                {"operation": "fake.cli.transaction"},
            )
            created = store.create_preview(
                transaction_id,
                {
                    "contract": "waapi-skill.fake-cli-preview/v1",
                    "request": json.loads(
                        json.dumps(request, ensure_ascii=False)
                    ),
                },
            )
            awaiting = store.submit_for_confirmation(transaction_id)
            self.transaction_ids[transaction_label] = transaction_id
            next_command = _fake_transaction_next_command(
                "transaction-show",
                ("transaction-show", transaction_id, "--summary-only"),
                requires_later_user_message=True,
            )
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "command": "preview",
                    "status": "awaiting_confirmation",
                    "state": awaiting.state.value,
                    "transaction_id": transaction_id,
                    "artifact_hash": created.artifact_hash,
                    "executed": False,
                    "verified": False,
                    "next_command": next_command,
                },
                0,
            )
        if step.subcommand not in {
            "transaction-show",
            "confirm",
            "execute",
            "verify",
        }:
            return ({"ok": True, "command": step.subcommand}, 0)
        transaction_id = self.transaction_ids[transaction_label]
        if step.subcommand == "transaction-show":
            snapshot = store.load_snapshot(transaction_id)
            token = snapshot.confirmation_token
            assert token is not None
            record = snapshot.record
            preview = snapshot.preview
            next_command = _fake_transaction_next_command(
                "confirm",
                (
                    "confirm",
                    transaction_id,
                    "--confirmation-token",
                    token,
                ),
                requires_explicit_user_confirmation=True,
            )
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "command": "transaction-show",
                    "status": "ok",
                    "state": record.state.value,
                    "transaction_id": transaction_id,
                    "artifact_hash": preview.artifact_hash,
                    "confirmation": {
                        "contract": "waapi-skill.confirmation-binding/v1",
                        "token": token,
                        "binding": {
                            "material_contract": (
                                "waapi-skill.confirmation-token-material/v1"
                            ),
                            "transaction_id": transaction_id,
                            "artifact_hash": preview.artifact_hash,
                            "state": record.state.value,
                            "event_sequence": record.event_sequence,
                            "last_event_hash": record.last_event_hash,
                        },
                    },
                    "next_command": next_command,
                },
                0,
            )
        if step.subcommand == "confirm":
            snapshot = store.load_snapshot(transaction_id)
            assert snapshot.confirmation_token is not None
            confirmed = store.confirm(
                transaction_id,
                confirmation_token=snapshot.confirmation_token,
            )
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "command": "confirm",
                    "status": "confirmed",
                    "state": confirmed.state.value,
                    "transaction_id": transaction_id,
                    "artifact_hash": confirmed.artifact_hash,
                    "next_command": _fake_transaction_next_command(
                        "execute",
                        ("execute", transaction_id),
                    ),
                },
                0,
            )
        if step.subcommand == "execute":
            store.begin_execution(
                transaction_id,
                expected_authorization=TransactionState.CONFIRMED,
            )
            if self.migration_indeterminate or self.ordinary_indeterminate:
                indeterminate = store.mark_execution_indeterminate(
                    transaction_id,
                    details={"automatic_retry": False},
                )
                return (
                    {
                        "contract": "waapi-skill.gateway-result/v1",
                        "ok": False,
                        "command": "execute",
                        "status": "indeterminate",
                        "state": indeterminate.state.value,
                        "automatic_retry": False,
                        "transaction_id": transaction_id,
                        "artifact_hash": indeterminate.artifact_hash,
                    },
                    2,
                )
            executed = store.mark_executed_unverified(transaction_id)
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "command": "execute",
                    "status": "executed_unverified",
                    "state": executed.state.value,
                    "executed": True,
                    "verified": False,
                    "automatic_retry": False,
                    "transaction_id": transaction_id,
                    "artifact_hash": executed.artifact_hash,
                    "next_command": _fake_transaction_next_command(
                        "verify",
                        ("verify", transaction_id),
                    ),
                },
                0,
            )
        if step.subcommand == "verify":
            verified = store.record_verification(
                transaction_id,
                TransactionState.RESULT_SCHEMA_CHECKED,
                details={"verification_strength": "fake_result_schema"},
            )
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "command": "verify",
                    "status": "result_schema_checked",
                    "state": verified.state.value,
                    "transaction_id": transaction_id,
                    "artifact_hash": verified.artifact_hash,
                },
                0,
            )
        raise AssertionError(step.subcommand)

    def _write_dispatch(self, evidence_directory: Path) -> None:
        assert self.runtime is not None
        for index in range(2):
            path = evidence_directory / f"session-context-{index:02d}.json"
            self._write_dispatch_row(
                path,
                {
                    "ok": True,
                    "api": "ak.wwise.core.getProjectInfo",
                    "version": "2022.1",
                    "item_type": "function",
                    "category": "core",
                    "risk_level": "low",
                    "timeout": 120.0,
                    "dry_run": False,
                    "result": {
                        "id": "{11111111-1111-1111-1111-111111111111}",
                        "name": "BusinessHost",
                        "path": str(self.runtime.plan.business_server_project_path),
                        "platforms": [],
                        "languages": [],
                    },
                    "error_code": None,
                    "message": "ok",
                },
            )
        count = 2 if self.duplicate_dispatch else 1
        for index in range(count):
            path = evidence_directory / f"dispatch-{index:02d}.json"
            payload = {
                "ok": True,
                "api": self.runtime.plan.scenario.api,
                "version": "2022.1",
                "item_type": "function",
                "category": "cli",
                "risk_level": (
                    "high"
                    if self.runtime.plan.scenario.api == "ak.wwise.cli.migrate"
                    else "medium"
                ),
                "timeout": 120.0,
                "dry_run": False,
                "result": {"result": 0},
                "error_code": None,
                "message": "ok",
            }
            if self.dispatch_tamper:
                payload.update(self.dispatch_tamper)
            self._write_dispatch_row(path, payload)
        if self.extra_dispatch_api is not None:
            path = evidence_directory / "dispatch-extra.json"
            self._write_dispatch_row(
                path,
                {
                    "ok": True,
                    "api": self.extra_dispatch_api,
                    "version": "2022.1",
                    "item_type": "function",
                    "category": "core",
                    "risk_level": "low",
                    "timeout": 120.0,
                    "dry_run": False,
                    "result": {},
                    "error_code": None,
                    "message": "ok",
                },
            )

    @staticmethod
    def _write_dispatch_row(path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(
            json.dumps(
                {**payload, "evidence_path": str(path)},
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def dependencies(self) -> HeavyCliRunnerDependencies:
        return HeavyCliRunnerDependencies(
            environment_resolver=self.environment_resolver,
            port_allocator=self.port_allocator,
            lock_factory=self.lock_factory,
            materialize_runtime=self.materialize_runtime,
            task_runner=self.task_runner,
            phase_factory=self.phase_factory,
            backend_session_factory=self.backend_factory,
        )


def _make_prerequisites(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    console = root / "WwiseConsole"
    console.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    console.chmod(0o755)
    source = root / "sample-source"
    source.mkdir()
    project = source / "SampleProject.wproj"
    project.write_text(
        '<WwiseDocument WwiseVersion="v2022.1.0" WwiseBuild="8584">'
        "<ProjectInfo>"
        '<Project Name="Fixture" ID="{11111111-1111-1111-1111-111111111111}">'
        "<Platforms>"
        '<Platform Name="Windows" ID="{22222222-2222-2222-2222-222222222222}" '
        'ReferencePlatform="Windows"/>'
        "</Platforms>"
        "<LanguageList>"
        '<Language Name="SFX" ID="{33333333-3333-3333-3333-333333333333}"/>'
        '<Language Name="English(US)" ID="{44444444-4444-4444-4444-444444444444}"/>'
        "</LanguageList>"
        "<PropertyList>"
        '<Property Name="SoundBankHeaderFilePath" Value="GeneratedSoundBanks"/>'
        '<Property Name="SoundBankPaths"><ValueList>'
        '<Value Platform="Windows">GeneratedSoundBanks\\Windows</Value>'
        "</ValueList></Property>"
        '<Property Name="ExternalSourcesOutputPath"><ValueList>'
        '<Value Platform="Windows">ExternalSources\\Windows</Value>'
        "</ValueList></Property>"
        "</PropertyList>"
        '<MiscSettings><MiscSettingEntry Name="Cache">.cache</MiscSettingEntry></MiscSettings>'
        "</Project>"
        "</ProjectInfo>"
        "</WwiseDocument>",
        encoding="utf-8",
    )
    master_mixer = source / "Master-Mixer Hierarchy"
    master_mixer.mkdir()
    (master_mixer / "Default Work Unit.wwu").write_text(
        "<WwiseDocument><MasterMixerHierarchy><WorkUnit><ChildrenList><Bus>"
        "<ReferenceList>"
        '<Reference Name="Effect0"><Custom>'
        '<Effect ID="{F388642C-2218-41E6-9E5A-266312A2EB17}" '
        'PluginName="ReWwire Sender" CompanyID="64" '
        'PluginID="6368" PluginType="3"/>'
        "</Custom></Reference>"
        '<Reference Name="Effect1" PluginName="Auro Headphone" CompanyID="263" '
        'PluginID="1100" PluginType="3"><ObjectRef '
        'ID="{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}"/></Reference>'
        "</ReferenceList>"
        "</Bus></ChildrenList></WorkUnit></MasterMixerHierarchy></WwiseDocument>",
        encoding="utf-8",
    )
    actor_mixer = source / "Actor-Mixer Hierarchy"
    actor_mixer.mkdir()
    (actor_mixer / "Car Engine.wwu").write_text(
        "<WwiseDocument><AudioObjects><WorkUnit><ChildrenList>"
        '<Sound Name="Camaro SS - CrankcaseAudio REV" '
        'ID="{4CD69CEB-521B-4C27-84DC-FFAED616E091}"><ChildrenList>'
        "<SourcePlugin PluginName=\"CrankcaseAudio REV\" CompanyID=\"261\" "
        "PluginID=\"416\"><PluginInnerObjectList>"
        "<PluginInnerObject PluginName=\"EngineSimulationControlData\" "
        "CompanyID=\"261\" PluginID=\"417\"/>"
        "<PluginInnerObject PluginName=\"AccelDecelModelControlData\" "
        "CompanyID=\"261\" PluginID=\"418\"/>"
        "</PluginInnerObjectList></SourcePlugin></ChildrenList></Sound>"
        '<BlendContainer Name="Porsche 911 - Blend Container" '
        'ID="{97A58685-6231-4227-9BAB-451E089615A8}"/>'
        "</ChildrenList></WorkUnit></AudioObjects></WwiseDocument>",
        encoding="utf-8",
    )
    effects = source / "Effects"
    effects.mkdir()
    shutil.copy2(
        SAMPLE_PROJECT.parent / "Effects" / "Factory McDSP Effects.wwu",
        effects / "Factory McDSP Effects.wwu",
    )
    (effects / "Ambisonics.wwu").write_text(
        "<WwiseDocument><Effects><WorkUnit><ChildrenList>"
        '<Effect Name="SLS_Big_Church_AHP_02" '
        'ID="{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}" '
        'PluginName="Auro Headphone" CompanyID="263" '
        'PluginID="1100" PluginType="3"/>'
        '<Effect Name="City" ID="{0D70F925-AB3C-477A-A7CA-D0571B293302}" '
        'PluginName="Wwise Parametric EQ" CompanyID="0" PluginID="105" '
        'PluginType="3"/>'
        '<Effect Name="High_Pass_for_HEIGHT" '
        'ID="{F9627628-0B10-4272-BC30-D4C20423CB38}" '
        'PluginName="Wwise Parametric EQ" CompanyID="0" PluginID="105" '
        'PluginType="3"/>'
        "</ChildrenList></WorkUnit></Effects></WwiseDocument>",
        encoding="utf-8",
    )
    return console, project


def _options(tmp_path: Path) -> HeavyCliRunnerOptions:
    return HeavyCliRunnerOptions(
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
        auth_json=tmp_path / "auth.json",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=120.0,
        live_environment={},
    )


def _units() -> tuple[Any, ...]:
    return build_heavy_units(_suite_cli_cases())


def _run_fake(
    tmp_path: Path,
    unit: Any,
    *,
    source_project: Path | None = None,
    **world_options: Any,
) -> tuple[Any, _FakeWorld, Path]:
    console, generated_source = _make_prerequisites(tmp_path / "prerequisites")
    source = source_project or generated_source
    world = _FakeWorld(
        source_project=source,
        console_path=console,
        **world_options,
    )
    scenario_root = tmp_path / "scenario"
    outcome = run_heavy_cli_unit(
        unit,
        scenario_root=scenario_root,
        options=_options(tmp_path),
        dependencies=world.dependencies(),
    )
    return outcome, world, scenario_root


def _sealed_object(
    *,
    path: str = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
    language: str | None,
    marker: str,
) -> CliObjectRecord:
    return CliObjectRecord(
        path=path,
        object_id="{11111111-1111-1111-1111-111111111111}",
        object_type="Sound" if language is not None else "ActorMixer",
        name=path.rsplit("\\", 1)[-1],
        language=language,
        source_sha256=marker,
    )


def test_sealed_backend_canonicalizes_localized_keys_and_reads() -> None:
    english = _sealed_object(language="English", marker="english")
    backend = _SealedCliBackend(context={}, objects=(english,), events=())

    assert backend.read_localized_object(
        english.path,
        language="English(US)",
    ) is english
    assert backend.read_localized_object(english.path, language="English") is english


def test_sealed_backend_rejects_canonical_language_alias_duplicates() -> None:
    path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    with pytest.raises(_InfrastructureFailure, match="duplicate canonical"):
        _SealedCliBackend(
            context={},
            objects=(
                _sealed_object(path=path, language="English", marker="alias"),
                _sealed_object(path=path, language="English(US)", marker="canonical"),
            ),
            events=(),
        )


def test_sealed_backend_localized_reads_survive_but_path_only_read_fails_ambiguous() -> None:
    path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    english = _sealed_object(path=path, language="English(US)", marker="english")
    japanese = _sealed_object(path=path, language="Japanese", marker="japanese")
    backend = _SealedCliBackend(
        context={},
        objects=(english, japanese),
        events=(),
    )

    assert backend.read_localized_object(path, language="English") is english
    assert backend.read_localized_object(path, language="Japanese") is japanese
    with pytest.raises(_InfrastructureFailure, match="path-only.*ambiguous"):
        backend.read_object(path)


def test_sealed_backend_rejects_duplicate_unlocalized_objects_and_events() -> None:
    path = r"\Actor-Mixer Hierarchy\Default Work Unit\Control"
    with pytest.raises(_InfrastructureFailure, match="duplicate unlocalized"):
        _SealedCliBackend(
            context={},
            objects=(
                _sealed_object(path=path, language=None, marker="control-a"),
                _sealed_object(path=path.lower(), language=None, marker="control-b"),
            ),
            events=(),
        )

    event = CliEventRecord(
        path=r"\Events\Default Work Unit\Play_Voice",
        object_id="{11111111-1111-1111-1111-111111111111}",
        action_ids=(),
        target_ids=(),
        action_types=(),
    )
    with pytest.raises(_InfrastructureFailure, match="duplicate Event"):
        _SealedCliBackend(
            context={},
            objects=(),
            events=(event, replace(event, path=event.path.lower())),
        )


def test_tab_runtime_rejects_path_duplicate_before_path_only_snapshots() -> None:
    runtime = SimpleNamespace(
        plan=SimpleNamespace(
            operation="tabDelimitedImport",
            asset_spec={
                "expected": {
                    "objects": [
                        {"path": r"\Actor-Mixer Hierarchy\Voices\Line"},
                        {"path": r"\actor-mixer hierarchy\voices\line"},
                    ]
                }
            },
        )
    )

    with pytest.raises(_InfrastructureFailure, match="path-unique before/post"):
        _assert_tab_path_identity_closed(runtime)  # type: ignore[arg-type]


def test_public_contract_owns_exact_four_cli_apis() -> None:
    assert HEAVY_CLI_RUN_CONTRACT == "waapi-skill.codex-heavy-cli-run/v3"
    assert HEAVY_CLI_RUNNER_APIS == frozenset(CLI_APIS)
    assert len(HEAVY_CLI_REVIEWED_CASE_APIS) == 20
    assert set(HEAVY_CLI_REVIEWED_CASE_APIS.values()) == set(CLI_APIS)
    assert all(
        tuple(HEAVY_CLI_REVIEWED_CASE_APIS.values()).count(api) == 5
        for api in CLI_APIS
    )


@pytest.mark.parametrize(
    "scenario_id",
    ("O22-CLI-GENERATE-BANK-04", "O22-CLI-GENERATE-BANK-05"),
)
def test_reviewed_generate_bank_hash_matches_bundle_and_rejects_drift(
    scenario_id: str,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.id == scenario_id
    )

    assert (
        _reviewed_scenario_sha256(unit)
        == _REVIEWED_CLI_SCENARIO_SHA256[unit.scenario.id]
    )
    _validate_reviewed_cli_unit(unit)

    drifted = replace(
        unit,
        scenario=replace(
            unit.scenario,
            fixture={**unit.scenario.fixture, "tampered": True},
        ),
    )
    with pytest.raises(HeavyCliRunnerError, match="identity drifted"):
        _validate_reviewed_cli_unit(drifted)


@pytest.mark.parametrize("tamper", ("prompt", "fixture", "api", "id", "turns"))
def test_cli_runner_rejects_any_reviewed_scenario_identity_tamper_before_launch(
    tmp_path: Path,
    tamper: str,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    if tamper == "prompt":
        candidate = replace(
            unit,
            scenario=replace(unit.scenario, prompt=unit.scenario.prompt + " 篡改"),
        )
    elif tamper == "fixture":
        candidate = replace(
            unit,
            scenario=replace(
                unit.scenario,
                fixture={**unit.scenario.fixture, "tampered": True},
            ),
        )
    elif tamper == "api":
        candidate = replace(
            unit,
            scenario=replace(
                unit.scenario,
                api="ak.wwise.cli.generateSoundbank",
            ),
        )
    elif tamper == "id":
        candidate = replace(
            unit,
            scenario=replace(
                unit.scenario,
                id="O22-CLI-CONVERT-EXTERNAL-99",
            ),
        )
    else:
        candidate = replace(unit, turns=unit.turns[:-1])

    scenario_root = tmp_path / "scenario"
    with pytest.raises(HeavyCliRunnerError, match="reviewed"):
        run_heavy_cli_unit(
            candidate,
            scenario_root=scenario_root,
            options=_options(tmp_path),
        )
    assert not scenario_root.exists()


@pytest.mark.parametrize("api", sorted(CLI_APIS))
def test_cli_runner_writes_only_typed_business_sections_for_each_api(
    tmp_path: Path,
    api: str,
) -> None:
    unit = next(unit for unit in _units() if unit.scenario.api == api)
    outcome, world, _ = _run_fake(tmp_path, unit)

    assert outcome.status == "PASS", outcome.reason
    assert len(world.business_oracle_plans) == 1
    payload = world.business_oracle_plans[0].payload
    static = payload["static_expectation"]
    assert payload["fixture_spec"]["kind"] == "cli_prepared_runtime_v1"
    assert static["family"] == "cli"
    assert static["api"] == api
    assert static["request_provenance"] == outcome.checks["request_provenance"]
    assert payload["payload_bindings"]["primary_steps"] == ["tx01.execute"]
    names = [step.name for step in world.business_protocols[0].steps]
    assert payload["payload_bindings"]["verification_steps"] == [
        name for name in names if name != "tx01.execute"
    ]
    if api == "ak.wwise.cli.migrate":
        assert "tx01.verify" not in names


def test_cli_runner_fails_closed_when_typed_business_sections_are_missing(
    tmp_path: Path,
) -> None:
    unit = next(unit for unit in _units() if unit.scenario.api in CLI_APIS)

    with pytest.raises(_InfrastructureFailure, match="lacks typed sections"):
        _write_common_business_oracle_plan(
            scenario=unit.scenario,
            version=unit.version,
            scenario_root=tmp_path,
            protocol=object(),
            provenance=object(),
            runner="cli",
            typed_sections=None,  # type: ignore[arg-type]
        )


def test_cli_runner_rejects_typed_sections_bound_to_another_protocol(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    outcome, world, scenario_root = _run_fake(tmp_path, unit)
    assert outcome.status == "PASS", outcome.reason
    evidence = world.business_oracle_plans[0]
    sections = parse_cli_business_plan_sections(evidence.payload)
    static = MappingProxyType(
        {**sections.static_expectation, "protocol_sha256": "0" * 64}
    )
    cross_protocol_sections = replace(sections, static_expectation=static)
    provenance = SimpleNamespace(
        payload={"protocol": {"sha256": "0" * 64}},
        sha256=evidence.payload["provenance_sha256"],
    )

    with pytest.raises(_InfrastructureFailure, match="scenario/protocol"):
        _write_common_business_oracle_plan(
            scenario=unit.scenario,
            version=unit.version,
            scenario_root=scenario_root,
            protocol=world.business_protocols[0],
            provenance=provenance,
            runner="cli",
            typed_sections=cross_protocol_sections,
        )


@pytest.mark.parametrize("unit", _units(), ids=lambda unit: unit.unit_id)
def test_all_twenty_cli_units_run_through_closed_fake_lifecycle(
    tmp_path: Path,
    unit: Any,
) -> None:
    outcome, world, scenario_root = _run_fake(tmp_path, unit)

    assert outcome.status == "PASS", outcome.reason
    assert outcome.passed
    assert outcome.thread_id == "fake-memory-isolated-thread"
    assert outcome.as_dict()["contract"] == HEAVY_CLI_RUN_CONTRACT
    assert not (scenario_root / "owned").exists()
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["owned_state_retained"] is False
    assert world.lock is not None and world.lock.entered and world.lock.exited

    roles = [spec.role for spec in world.phase_specs]
    expected_roles = {
        "ak.wwise.cli.convertExternalSource": ["business"],
        "ak.wwise.cli.generateSoundbank": ["setup", "business"],
        "ak.wwise.cli.tabDelimitedImport": ["setup", "business", "oracle"],
        "ak.wwise.cli.migrate": ["business", "oracle"],
    }[unit.scenario.api]
    assert roles == expected_roles
    business = next(spec for spec in world.phase_specs if spec.role == "business")
    assert business.project_path == str(world.runtime.plan.business_server_project_path)
    assert str(world.runtime.plan.business_server_project_path) in business.argv
    assert dict(world.phase_project_exists)["business"] is True
    assert business.project_path != str(world.runtime.plan.project_path)
    assert business.project_path != str(world.source_project)
    assert world.backend_roles == [
        role for role in expected_roles if role in {"setup", "oracle"}
    ]
    assert world.business_expected_natural_exit is (
        unit.scenario.api == "ak.wwise.cli.migrate"
    )
    shown = next(
        record.payload
        for record in world.gateway_records
        if record.step_name == "tx01.transaction-show"
    )
    binding = outcome.checks["tx01.transaction-show.confirmation_binding"]
    assert shown["confirmation"] == {
        "contract": "waapi-skill.confirmation-binding/v1",
        "token": binding["token"],
        "binding": {
            "material_contract": "waapi-skill.confirmation-token-material/v1",
            "transaction_id": binding["transaction_id"],
            "artifact_hash": binding["artifact_hash"],
            "state": "awaiting_confirmation",
            "event_sequence": binding["event_sequence"],
            "last_event_hash": binding["last_event_hash"],
        },
    }
    assert shown["next_command"] == _fake_transaction_next_command(
        "confirm",
        (
            "confirm",
            binding["transaction_id"],
            "--confirmation-token",
            binding["token"],
        ),
        requires_explicit_user_confirmation=True,
    )


@pytest.mark.parametrize(
    ("case_id", "required_languages"),
    [
        (
            "O22-CLI-GENERATE-BANK-02",
            {"English(US)", "Japanese", "Chinese(PRC)"},
        ),
        ("O22-CLI-TAB-IMPORT-01", {"English(US)", "Japanese"}),
    ],
)
def test_cli_prelaunch_normalizes_real_project_copy_before_materialize_without_source_drift(
    tmp_path: Path,
    case_id: str,
    required_languages: set[str],
) -> None:
    unit = next(unit for unit in _units() if unit.scenario.id == case_id)
    source_sha256 = hashlib.sha256(SAMPLE_PROJECT.read_bytes()).hexdigest()

    outcome, world, _ = _run_fake(
        tmp_path,
        unit,
        source_project=SAMPLE_PROJECT,
    )

    assert outcome.status == "PASS", outcome.reason
    assert required_languages.issubset(world.materialize_project_languages)
    assert outcome.checks["project_prelaunch_languages"] == [
        language
        for language in ("Japanese", "Chinese(PRC)")
        if language in required_languages
    ]
    assert outcome.checks["source_template_unchanged"] is True
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["source_hash_before"] == outcome.lifecycle["source_hash_after"]
    assert hashlib.sha256(SAMPLE_PROJECT.read_bytes()).hexdigest() == source_sha256


def test_cli_first_use_intro_rejects_a_later_agent_message(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    outcome, world, scenario_root = _run_fake(
        tmp_path,
        unit,
        delay_first_use_intro=True,
    )

    assert outcome.status == "FAIL"
    assert "first Skill-backed response lacks session context" in outcome.reason
    assert (scenario_root / "owned").is_dir()


def test_migration_runner_shutdown_is_not_classified_as_a_disconnect(
    tmp_path: Path,
) -> None:
    unit = next(
        unit for unit in _units() if unit.scenario.api == "ak.wwise.cli.migrate"
    )
    outcome, world, _ = _run_fake(
        tmp_path,
        unit,
        migration_indeterminate=True,
    )

    assert outcome.status == "PASS", outcome.reason
    assert world.business_returncode == 2
    assert outcome.checks["primary_dispatch"] == {
        "api": "ak.wwise.cli.migrate",
        "count": 1,
        "connection_lost": False,
        "connection_lost_after_dispatch": False,
    }
    assert outcome.lifecycle is not None
    business = outcome.lifecycle["phases"][0]["evidence"]
    assert business["natural_exit_before_shutdown"] is False
    assert business["runner_shutdown_requested"] is True


def test_migration_natural_control_exit_is_classified_after_one_dispatch(
    tmp_path: Path,
) -> None:
    unit = next(
        unit for unit in _units() if unit.scenario.api == "ak.wwise.cli.migrate"
    )
    outcome, _world, _ = _run_fake(
        tmp_path,
        unit,
        natural_business_exit=True,
    )

    assert outcome.status == "PASS", outcome.reason
    assert outcome.checks["primary_dispatch"] == {
        "api": "ak.wwise.cli.migrate",
        "count": 1,
        "connection_lost": True,
        "connection_lost_after_dispatch": True,
    }
    assert outcome.lifecycle is not None
    business = outcome.lifecycle["phases"][0]["evidence"]
    assert business["natural_exit_before_shutdown"] is True
    assert business["runner_shutdown_requested"] is False


@pytest.mark.parametrize(("api", "operation"), tuple(CLI_APIS.items()))
def test_only_reviewed_2022_result_two_warning_diagnostics_are_classified(
    api: str,
    operation: str,
) -> None:
    lines = ("Warning: Project load issue accepted by automation.",)
    classified, unclassified = _classify_load_issues(
        version="2022.1",
        api=api,
        operation=operation,
        process_result=2,
        lines=lines,
    )
    assert classified == lines
    assert unclassified == []

    for version, candidate_api, candidate_operation, result in (
        ("2023.1", api, operation, 2),
        ("2022.1", "ak.wwise.cli.verify", operation, 2),
        ("2022.1", api, operation, 1),
        ("2022.1", api, "migrate" if operation != "migrate" else "generateSoundbank", 2),
    ):
        classified, unclassified = _classify_load_issues(
            version=version,
            api=candidate_api,
            operation=candidate_operation,
            process_result=result,
            lines=lines,
        )
        assert classified == ()
        assert unclassified == list(lines)

    classified, unclassified = _classify_load_issues(
        version="2022.1",
        api=api,
        operation=operation,
        process_result=2,
        lines=("Error: Project load issue with an unknown asset.",),
    )
    assert classified == ()
    assert unclassified == ["Error: Project load issue with an unknown asset."]


def test_load_issue_scan_preserves_and_classifies_more_than_twenty_warnings() -> None:
    warnings = tuple(
        f"Warning: Project load issue {index:02d}." for index in range(37)
    )
    lines = _load_issue_lines("\n".join(warnings), "")

    assert lines == warnings
    classified, unclassified = _classify_load_issues(
        version="2022.1",
        api="ak.wwise.cli.convertExternalSource",
        operation="convertExternalSource",
        process_result=2,
        lines=lines,
    )
    assert classified == warnings
    assert unclassified == []


def test_load_issue_scan_keeps_error_after_many_warnings_unclassified() -> None:
    warnings = tuple(
        f"Warning: Project load issue {index:02d}." for index in range(41)
    )
    error = "Error: Project load issue 41 was fatal."
    stdout = "\n".join(
        (*warnings, warnings[0], error)
    )
    lines = _load_issue_lines(stdout, "")

    assert lines == (*warnings, error)
    classified, unclassified = _classify_load_issues(
        version="2022.1",
        api="ak.wwise.cli.convertExternalSource",
        operation="convertExternalSource",
        process_result=2,
        lines=lines,
    )
    assert classified == ()
    assert unclassified == list(lines)


def test_load_issue_scan_preserves_late_severity_in_a_long_line() -> None:
    warning = "Warning: Project load issue contains " + ("detail " * 90) + "fatal error."
    lines = _load_issue_lines(warning, "")

    assert lines == (warning,)
    classified, unclassified = _classify_load_issues(
        version="2022.1",
        api="ak.wwise.cli.tabDelimitedImport",
        operation="tabDelimitedImport",
        process_result=2,
        lines=lines,
    )
    assert classified == ()
    assert unclassified == [warning]


def test_load_issue_scan_deduplicates_across_bounded_streams_in_first_seen_order() -> None:
    first = "Warning: Project load issue alpha."
    second = "Warning: Project load issue beta."
    third = "Warning: Project load issue gamma."

    assert _load_issue_lines(
        "\n".join((first, second, first)),
        "\n".join((second, third, first)),
    ) == (first, second, third)


def test_load_issue_scan_fails_closed_above_process_log_byte_ceiling() -> None:
    assert _load_issue_lines("x" * MAX_LOG_BYTES, "") == ()
    with pytest.raises(_SemanticFailure, match="process-log byte ceiling"):
        _load_issue_lines("x" * (MAX_LOG_BYTES + 1), "")


def test_migration_indeterminate_without_matching_outer_state_stays_indeterminate(
    tmp_path: Path,
) -> None:
    unit = next(
        unit for unit in _units() if unit.scenario.api == "ak.wwise.cli.migrate"
    )
    outcome, _world, scenario_root = _run_fake(
        tmp_path,
        unit,
        migration_indeterminate=True,
        apply_business=False,
    )

    assert outcome.status == "INDETERMINATE"
    assert (scenario_root / "owned").is_dir()
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["owned_state_retained"] is True


def test_ordinary_exact_indeterminate_stops_before_verify_and_is_classified(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.generateSoundbank"
    )
    outcome, world, scenario_root = _run_fake(
        tmp_path,
        unit,
        ordinary_indeterminate=True,
    )

    assert outcome.status == "INDETERMINATE"
    assert outcome.checks["task_terminal_indeterminate"] is True
    assert outcome.checks["task_passed"] is False
    assert outcome.checks["failure_classification"] == "INDETERMINATE"
    assert (scenario_root / "owned").is_dir()
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["owned_state_retained"] is True

    assert "tx01.execute" in world.executed_step_names
    assert "tx01.verify" not in world.executed_step_names


def test_cli_blocks_before_launch_when_control_template_has_a_symlink(
    tmp_path: Path,
) -> None:
    unit = next(
        unit for unit in _units() if unit.scenario.api == "ak.wwise.cli.migrate"
    )
    console, source = _make_prerequisites(tmp_path / "prerequisites")
    outside = tmp_path / "outside.wwu"
    outside.write_text("outside", encoding="utf-8")
    (source.parent / "escaped.wwu").symlink_to(outside)
    world = _FakeWorld(source_project=source, console_path=console)

    outcome = run_heavy_cli_unit(
        unit,
        scenario_root=tmp_path / "scenario",
        options=_options(tmp_path),
        dependencies=world.dependencies(),
    )

    assert outcome.status == "BLOCKED"
    assert "project tree contains a symlink" in outcome.reason
    assert world.phase_specs == []


@pytest.mark.parametrize(
    ("category", "turn_failed", "timed_out"),
    [
        ("quota_or_rate_limit", True, False),
        ("authentication", False, False),
    ],
)
def test_pre_agent_codex_infrastructure_failure_archives_closed_checks(
    tmp_path: Path,
    category: str,
    turn_failed: bool,
    timed_out: bool,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    console, source = _make_prerequisites(tmp_path / "prerequisites")
    world = _FakeWorld(source_project=source, console_path=console)
    failure = CodexInfrastructureFailure(
        category=category,
        message="runner-visible diagnostic that is not part of closed checks",
        turn_failed=turn_failed,
        timed_out=timed_out,
        agent_item_event_count=0,
    )

    def fail(**_kwargs):
        raise CodexInfrastructureError(failure, SimpleNamespace())  # type: ignore[arg-type]

    dependencies = replace(world.dependencies(), task_runner=fail)
    root = tmp_path / "scenario"
    outcome = run_heavy_cli_unit(
        unit,
        scenario_root=root,
        options=_options(tmp_path),
        dependencies=dependencies,
    )
    expected = {
        "category": category,
        "turn_failed": turn_failed,
        "timed_out": timed_out,
        "agent_item_event_count": 0,
    }

    assert outcome.status == "BLOCKED"
    assert outcome.checks["failure_classification"] == "BLOCKED"
    assert outcome.checks["codex_infrastructure_failure"] == expected
    assert set(outcome.checks["codex_infrastructure_failure"]) == set(expected)
    persisted = json.loads((root / "outcome.json").read_text(encoding="utf-8"))
    assert persisted["checks"]["codex_infrastructure_failure"] == expected


def test_ordinary_task_error_does_not_claim_pre_agent_codex_evidence(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    console, source = _make_prerequisites(tmp_path / "prerequisites")
    world = _FakeWorld(source_project=source, console_path=console)

    def fail(**_kwargs):
        raise RuntimeError("ordinary task adapter error")

    dependencies = replace(world.dependencies(), task_runner=fail)
    outcome = run_heavy_cli_unit(
        unit,
        scenario_root=tmp_path / "scenario",
        options=_options(tmp_path),
        dependencies=dependencies,
    )

    assert outcome.status == "BLOCKED"
    assert "codex_infrastructure_failure" not in outcome.checks


def test_codex_infrastructure_failure_does_not_hide_business_phase_blocker(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    console, source = _make_prerequisites(tmp_path / "prerequisites")
    world = _FakeWorld(
        source_project=source,
        console_path=console,
        residual_role="business",
    )
    failure = CodexInfrastructureFailure(
        category="quota_or_rate_limit",
        message="synthetic quota failure",
        turn_failed=True,
        timed_out=False,
        agent_item_event_count=0,
    )

    def fail(**_kwargs):
        raise CodexInfrastructureError(failure, SimpleNamespace())  # type: ignore[arg-type]

    outcome = run_heavy_cli_unit(
        unit,
        scenario_root=tmp_path / "scenario",
        options=_options(tmp_path),
        dependencies=replace(world.dependencies(), task_runner=fail),
    )

    assert outcome.status == "BLOCKED"
    assert outcome.lifecycle is not None
    assert any("residual WwiseConsole" in item for item in outcome.lifecycle["errors"])
    assert outcome.checks["codex_infrastructure_failure"]["category"] == (
        "quota_or_rate_limit"
    )


def test_duplicate_primary_dispatch_is_semantic_fail_and_retains_quarantine(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    outcome, _world, scenario_root = _run_fake(
        tmp_path,
        unit,
        duplicate_dispatch=True,
    )

    assert outcome.status == "FAIL"
    assert "dispatched exactly once" in outcome.reason
    assert (scenario_root / "owned").is_dir()
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["owned_state_retained"] is True
    assert Path(outcome.lifecycle["quarantine_path"]).is_file()


@pytest.mark.parametrize(
    ("world_options", "reason_fragment"),
    [
        ({"dispatch_tamper": {"version": "2023.1"}}, "version is not 2022.1"),
        (
            {"dispatch_tamper": {"contract": "forged/unknown"}},
            "success schema drifted",
        ),
        (
            {"dispatch_tamper": {"result": {"result": True}}},
            "process-result schema is invalid",
        ),
        (
            {"dispatch_tamper": {"api": "ak.wwise.cli.migrate"}},
            "unreviewed URI",
        ),
        (
            {"extra_dispatch_api": "ak.wwise.core.getInfo"},
            "unreviewed URI",
        ),
    ],
)
def test_dispatcher_evidence_tamper_is_semantic_fail_and_retains_quarantine(
    tmp_path: Path,
    world_options: Mapping[str, Any],
    reason_fragment: str,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    outcome, _world, scenario_root = _run_fake(
        tmp_path,
        unit,
        **dict(world_options),
    )

    assert outcome.status == "FAIL"
    assert reason_fragment in outcome.reason
    assert (scenario_root / "owned").is_dir()
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["owned_state_retained"] is True


def test_missing_tab_business_effect_is_semantic_fail_and_retains_state(
    tmp_path: Path,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.tabDelimitedImport"
    )
    outcome, _world, scenario_root = _run_fake(
        tmp_path,
        unit,
        apply_business=False,
    )

    assert outcome.status == "FAIL"
    assert not outcome.checks["business_verification"]["verification"]["passed"]
    assert (scenario_root / "owned").is_dir()


@pytest.mark.parametrize(
    ("world_options", "reason_fragment"),
    [
        ({"residual_role": "business"}, "residual WwiseConsole processes"),
        ({"mutate_source": True}, "immutable source project"),
        ({"fail_lock_release": True}, "lifecycle-lock-release"),
    ],
)
def test_cleanup_or_source_proof_fault_blocks_and_never_deletes_owned_state(
    tmp_path: Path,
    world_options: Mapping[str, Any],
    reason_fragment: str,
) -> None:
    unit = next(
        unit
        for unit in _units()
        if unit.scenario.api == "ak.wwise.cli.convertExternalSource"
    )
    outcome, _world, scenario_root = _run_fake(
        tmp_path,
        unit,
        **dict(world_options),
    )

    assert outcome.status == "BLOCKED"
    assert reason_fragment in outcome.reason
    assert (scenario_root / "owned").is_dir()
    assert outcome.lifecycle is not None
    assert outcome.lifecycle["owned_state_retained"] is True

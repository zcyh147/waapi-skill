"""Trusted Harbor SoundBank fixture and oracle for integration workflows.

This module composes the existing SoundBank generation materializer with a
two-transaction workflow.  It does not start Wwise or Codex.  The caller owns
the :class:`ScenarioRuntime` lifecycle and must leave failed or indeterminate
state to that lifecycle's quarantine path.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from tests.semantic.support.codex_campaign import atomic_write_json_with_digest
from tests.semantic.support.codex_eval_bundle_v3 import (
    ExpectedDispatch,
    OnlineScenario,
    VisibleInput,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep
from tests.semantic.support.codex_integration_workflows_v1 import (
    IntegrationPrimaryDispatch,
    IntegrationScenarioProxy,
    IntegrationWorkflowCase,
)
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioRuntime
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    MASTER_AUDIO_BUS,
    BankState,
    ClosedDirectWaapiSoundBankBackend,
    DirectWaapiCall,
    ExpectedArtifact,
    InclusionRow,
    MaterializedSoundBankCase,
    PROJECT_INFO_OBSERVER_MAX_PLATFORM_ROWS,
    PreparedSoundBankRuntime,
    SoundBankBlueprint,
    SoundBankRuntimeBackend,
    SoundBankSnapshot,
    build_soundbank_blueprint,
)


HARBOR_WORKFLOW_ID = "harbor_soundbank_release"
HARBOR_FIXTURE_ADAPTER = "harbor_soundbank_fixture_v1"
HARBOR_RELEASE_BANK = "Harbor_Release"
HARBOR_CONTROL_BANK = "Harbor_Control"
HARBOR_DEBUG_EVENT = "Play_Harbor_Debug"
HARBOR_BUS_NAME = "Harbor Bus"
HARBOR_PLATFORMS = ("Windows", "Mac")
HARBOR_FILTERS = ("events", "structures", "media")
HARBOR_PROJECT_INFO_PATH_EVIDENCE_CONTRACT = (
    "waapi-skill.harbor-project-info-host-paths/v1"
)
HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE = "harbor-project-info-host-paths.json"
HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES = 4096
HARBOR_PROJECT_INFO_MAX_PLATFORM_ROWS = PROJECT_INFO_OBSERVER_MAX_PLATFORM_ROWS
SET_INCLUSIONS_API = "ak.wwise.core.soundbank.setInclusions"
GENERATE_API = "ak.wwise.core.soundbank.generate"
REQUIRED_REFERENCE = "references/waapi-operate.md"
_GENERATION_VISIBLE_INPUTS = (
    VisibleInput(
        "generation_request",
        "structured_object",
        "封闭的 Harbor 双平台 SoundBank 生成请求",
    ),
    VisibleInput(
        "build_locations",
        "structured_object",
        "当前案例的双平台生成位置",
    ),
)


class HarborIntegrationRuntimeError(RuntimeError):
    """The Harbor integration fixture or independent oracle failed closed."""


@dataclass(frozen=True, slots=True)
class HarborOracleRequirement:
    transaction_id: str
    expectation: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "expectation": _plain(self.expectation),
        }


@dataclass(frozen=True, slots=True)
class HarborIntegrationVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    before: SoundBankSnapshot
    after: SoundBankSnapshot
    evidence: Mapping[str, Any]

    def assert_passed(self) -> None:
        if not self.passed:
            raise HarborIntegrationRuntimeError(
                f"Harbor {self.phase} verification failed: "
                + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class PreparedHarborIntegrationRuntime:
    prompt: str
    visible_values: Mapping[str, str]
    protocol: V3GatewayProtocol
    snapshot: Callable[[], SoundBankSnapshot]
    verify_final: Callable[
        [Mapping[str, Any] | None, Any],
        HarborIntegrationVerification,
    ]
    cleanup: Callable[[], tuple[str, ...]]
    observe_payload: Callable[
        [ExpectedGatewayStep, Mapping[str, Any]],
        None,
    ]
    expected_dispatches: tuple[IntegrationPrimaryDispatch, ...]
    oracle_requirements: tuple[HarborOracleRequirement, ...]
    prompt_sources: Mapping[str, Any]
    host_path_evidence_path: Path
    required_reference: str = REQUIRED_REFERENCE


BackendFactory = Callable[[SoundBankBlueprint], SoundBankRuntimeBackend]


def prepare_harbor_integration_runtime(
    workflow: IntegrationWorkflowCase,
    scenario: IntegrationScenarioProxy,
    *,
    version: str,
    runtime: ScenarioRuntime,
    direct: DirectWaapiCall,
) -> PreparedHarborIntegrationRuntime:
    """Prepare the Harbor workflow against one already-running owned project."""

    if not callable(direct):
        raise TypeError("direct must be callable")
    return _prepare_harbor_integration_runtime(
        workflow,
        scenario,
        version=version,
        runtime=runtime,
        backend_factory=lambda _blueprint: ClosedDirectWaapiSoundBankBackend(
            direct
        ),
    )


def _prepare_harbor_integration_runtime(
    workflow: IntegrationWorkflowCase,
    scenario: IntegrationScenarioProxy,
    *,
    version: str,
    runtime: ScenarioRuntime,
    backend_factory: BackendFactory,
) -> PreparedHarborIntegrationRuntime:
    _validate_inputs(workflow, scenario, version=version, runtime=runtime)
    generated_scenario = _generation_scenario(
        workflow,
        scenario,
        version=version,
    )
    blueprint = build_soundbank_blueprint(
        generated_scenario,
        version=version,
        sandbox_project=runtime.sandbox.sandbox_project,
        io_root=runtime.owned_root,
        asset_root=runtime.asset_root / "harbor-soundbank",
    )
    blueprint = _harbor_prestate_blueprint(blueprint, workflow)
    backend = backend_factory(blueprint)
    path_evidence = _HarborProjectInfoPathEvidenceRecorder(
        runtime.evidence_root / HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE,
        scenario_id=scenario.id,
        version=version,
    )
    soundbank_runtime = PreparedSoundBankRuntime(
        blueprint,
        backend,
        project_info_observer=path_evidence.observe,
    )
    materialized = soundbank_runtime.prepare()
    before = soundbank_runtime.hidden_before
    if before is None:
        raise HarborIntegrationRuntimeError(
            "Harbor SoundBank materializer omitted its before snapshot"
        )

    event_paths = _formal_event_paths(workflow)
    visible_values = _integration_visible_values(
        workflow,
        scenario,
        runtime=runtime,
        materialized=materialized,
        event_paths=event_paths,
    )
    set_request = _set_inclusions_request(
        version=version,
        event_paths=event_paths,
    )
    if len(materialized.operation_requests) != 1:
        raise HarborIntegrationRuntimeError(
            "Harbor generation materializer must produce exactly one request"
        )
    generation_request = _validated_generation_request(
        materialized.operation_requests[0],
        io_root=runtime.owned_root,
        output_root=visible_values["soundbank_output_directory"],
        project_info=materialized.prompt_sources.get(
            "soundbank_generate_project_info"
        ),
    )
    protocol = build_transaction_protocol(
        (set_request, generation_request)
    )
    expected_dispatches = (
        IntegrationPrimaryDispatch(
            SET_INCLUSIONS_API,
            1,
            "replace Harbor_Release with exactly the three formal Event, "
            "Structure, and Media inclusions",
        ),
        IntegrationPrimaryDispatch(
            GENERATE_API,
            1,
            "generate only Harbor_Release for Windows and Mac",
        ),
    )
    oracle_requirements = _oracle_requirements(
        materialized,
        event_paths=event_paths,
    )
    adapter = _HarborIntegrationAdapter(
        soundbank_runtime=soundbank_runtime,
        materialized=materialized,
        initial=before,
        event_paths=event_paths,
    )
    prompt_sources = {
        **_plain(materialized.prompt_sources),
        "harbor_output_root": visible_values["soundbank_output_directory"],
        "harbor_io_root": visible_values["soundbank_io_root"],
        "harbor_event_paths": list(event_paths),
    }
    return PreparedHarborIntegrationRuntime(
        prompt=scenario.render_prompt(visible_values),
        visible_values=MappingProxyType(dict(visible_values)),
        protocol=protocol,
        snapshot=adapter.snapshot,
        verify_final=adapter.verify_final,
        cleanup=adapter.cleanup,
        observe_payload=adapter.observe_payload,
        expected_dispatches=expected_dispatches,
        oracle_requirements=oracle_requirements,
        prompt_sources=_freeze_mapping(prompt_sources),
        host_path_evidence_path=path_evidence.path,
    )


class _HarborProjectInfoPathEvidenceRecorder:
    """Archive exact pre-normalization path spellings from getProjectInfo."""

    def __init__(self, path: Path, *, scenario_id: str, version: str) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise HarborIntegrationRuntimeError(
                "Harbor project-info path evidence requires an absolute path"
            )
        digest_path = self.path.with_name(self.path.name + ".sha256")
        if (
            self.path.exists()
            or self.path.is_symlink()
            or digest_path.exists()
            or digest_path.is_symlink()
        ):
            raise HarborIntegrationRuntimeError(
                f"Harbor project-info path evidence cannot be reused: {self.path}"
            )
        self._scenario_id = scenario_id
        self._version = version
        self._observations: list[Mapping[str, Any]] = []

    def observe(self, project_info: Mapping[str, Any]) -> None:
        if not isinstance(project_info, Mapping):
            raise HarborIntegrationRuntimeError(
                "Harbor getProjectInfo path evidence requires an object"
            )
        if len(self._observations) >= 2:
            raise HarborIntegrationRuntimeError(
                "Harbor getProjectInfo path evidence exceeded two observations"
            )
        paths, platform_row_count, omitted_platform_rows = (
            _raw_project_info_host_paths(project_info)
        )
        observation = {
            "index": len(self._observations) + 1,
            "platform_row_count": platform_row_count,
            "omitted_platform_rows": omitted_platform_rows,
            "paths": paths,
        }
        self._observations.append(observation)
        atomic_write_json_with_digest(
            self.path,
            {
                "contract": HARBOR_PROJECT_INFO_PATH_EVIDENCE_CONTRACT,
                "scenario_id": self._scenario_id,
                "version": self._version,
                "source": "ak.wwise.core.getProjectInfo",
                "model_visible": False,
                "normalization_applied": False,
                "observation_count": len(self._observations),
                "observations": list(self._observations),
            },
        )


def _raw_project_info_host_paths(
    project_info: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], int | None, int]:
    rows: list[Mapping[str, Any]] = [
        _raw_host_path_evidence("project_info.path", project_info.get("path"))
    ]
    directories = project_info.get("directories")
    for field in ("root", "cache", "soundBankOutputRoot"):
        rows.append(
            _raw_host_path_evidence(
                f"project_info.directories.{field}",
                directories.get(field) if isinstance(directories, Mapping) else None,
            )
        )
    platforms = project_info.get("platforms")
    platform_row_count = project_info.get("platform_count")
    omitted_platform_rows = project_info.get("omitted_platform_rows")
    if (
        not isinstance(platforms, list)
        or (
            platform_row_count is not None
            and (
                isinstance(platform_row_count, bool)
                or not isinstance(platform_row_count, int)
                or platform_row_count < 0
            )
        )
        or isinstance(omitted_platform_rows, bool)
        or not isinstance(omitted_platform_rows, int)
        or omitted_platform_rows < 0
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor project-info observer projection is malformed"
        )
    expected_recorded = (
        0
        if platform_row_count is None
        else min(platform_row_count, HARBOR_PROJECT_INFO_MAX_PLATFORM_ROWS)
    )
    expected_omitted = (
        0 if platform_row_count is None else platform_row_count - expected_recorded
    )
    if (
        len(platforms) != expected_recorded
        or omitted_platform_rows != expected_omitted
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor project-info observer projection count is inconsistent"
        )
    if platform_row_count is not None:
        for index in range(len(platforms)):
            platform = platforms[index]
            for field in ("soundBankPath", "copiedMediaPath"):
                rows.append(
                    _raw_host_path_evidence(
                        f"project_info.platforms[{index}].{field}",
                        platform.get(field) if isinstance(platform, Mapping) else None,
                    )
                )
    return rows, platform_row_count, omitted_platform_rows


def _raw_host_path_evidence(
    field: str,
    value: Any,
) -> Mapping[str, Any]:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        byte_count: int | None = len(encoded)
        raw_omitted = byte_count > HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES
        raw_value: str | None = None if raw_omitted else value
        trailing_separator: bool | None = value.endswith(("/", "\\"))
        if value.startswith(("\\\\", "//")):
            lexical_flavor = "unc"
        elif len(value) >= 3 and value[0].isalpha() and value[1] == ":":
            lexical_flavor = "windows-drive"
        elif value.startswith("/"):
            lexical_flavor = "posix"
        else:
            lexical_flavor = "unknown"
        raw_sha256: str | None = hashlib.sha256(encoded).hexdigest()
    else:
        raw_value = None
        raw_omitted = False
        trailing_separator = None
        lexical_flavor = "non-string"
        byte_count = None
        raw_sha256 = None
    return {
        "field": field,
        "raw_value": raw_value,
        "raw_type": type(value).__name__,
        "utf8_bytes": byte_count,
        "raw_utf8_limit": HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES,
        "raw_omitted": raw_omitted,
        "raw_sha256": raw_sha256,
        "lexical_flavor": lexical_flavor,
        "trailing_separator": trailing_separator,
    }


class _HarborIntegrationAdapter:
    def __init__(
        self,
        *,
        soundbank_runtime: PreparedSoundBankRuntime,
        materialized: MaterializedSoundBankCase,
        initial: SoundBankSnapshot,
        event_paths: tuple[str, ...],
    ) -> None:
        self.soundbank_runtime = soundbank_runtime
        self.materialized = materialized
        self.initial = initial
        self.event_paths = event_paths
        self.generation_baseline: SoundBankSnapshot | None = None
        self.final_verification: HarborIntegrationVerification | None = None

    def snapshot(self) -> SoundBankSnapshot:
        return self.soundbank_runtime.snapshot()

    def observe_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        if not isinstance(step, ExpectedGatewayStep):
            raise HarborIntegrationRuntimeError(
                "Harbor observer received an invalid gateway step"
            )
        if not isinstance(payload, Mapping):
            raise HarborIntegrationRuntimeError(
                "Harbor observer payload must be an object"
            )
        if step.name == "tx01.verify":
            if self.generation_baseline is not None:
                raise HarborIntegrationRuntimeError(
                    "Harbor tx01 verification was observed more than once"
                )
            verification = self._verify_tx01()
            verification.assert_passed()
            self.generation_baseline = verification.after
            return
        if step.name == "tx02.preview":
            baseline = self.generation_baseline
            if baseline is None:
                raise HarborIntegrationRuntimeError(
                    "Harbor generation preview preceded tx01 verified readback"
                )
            current = self.soundbank_runtime.snapshot()
            failures = _snapshot_field_drift(
                baseline,
                current,
                fields=(
                    "objects",
                    "banks",
                    "project_files",
                    "input_files",
                    "output_files",
                ),
                label="tx02 preview",
            )
            if failures:
                raise HarborIntegrationRuntimeError("; ".join(failures))

    def verify_final(
        self,
        _payload: Mapping[str, Any] | None,
        _result: Any,
    ) -> HarborIntegrationVerification:
        if self.final_verification is not None:
            raise HarborIntegrationRuntimeError(
                "Harbor final verification is single-use"
            )
        baseline = self.generation_baseline
        after = self.soundbank_runtime.snapshot(save=True)
        failures: list[str] = []
        if baseline is None:
            failures.append(
                "tx01.verify did not establish the generation baseline"
            )
            baseline = self.initial
        else:
            failures.extend(
                _snapshot_field_drift(
                    baseline,
                    after,
                    fields=("objects", "banks", "project_files", "input_files"),
                    label="generation",
                )
            )
            failures.extend(
                _verify_release_inclusions(
                    self.materialized,
                    after,
                    event_paths=self.event_paths,
                )
            )
            failures.extend(
                _verify_control_bank_unchanged(
                    baseline,
                    after,
                )
            )
        failures.extend(
            _verify_generation_artifacts(
                self.materialized,
                baseline,
                after,
            )
        )
        verification = HarborIntegrationVerification(
            phase="final",
            passed=not failures,
            failures=tuple(failures),
            before=baseline,
            after=after,
            evidence=_freeze_mapping(
                {
                    "target_bank": HARBOR_RELEASE_BANK,
                    "platforms": HARBOR_PLATFORMS,
                    "formal_event_paths": self.event_paths,
                    "required_artifact_count": len(
                        [
                            row
                            for row in self.materialized.expected_artifacts
                            if row.required_change
                        ]
                    ),
                    "init_policy": "optional_nonempty_and_reported_separately",
                }
            ),
        )
        self.final_verification = verification
        return verification

    def cleanup(self) -> tuple[str, ...]:
        if (
            self.final_verification is None
            or self.final_verification.passed is not True
        ):
            raise HarborIntegrationRuntimeError(
                "Harbor cleanup is allowed only after successful final verification; "
                "failed state belongs to lifecycle quarantine"
            )
        return self.soundbank_runtime.cleanup_success()

    def _verify_tx01(self) -> HarborIntegrationVerification:
        after = self.soundbank_runtime.snapshot(save=True)
        failures = _verify_release_inclusions(
            self.materialized,
            after,
            event_paths=self.event_paths,
        )
        failures.extend(
            _snapshot_field_drift(
                self.initial,
                after,
                fields=("objects", "input_files", "output_files"),
                label="setInclusions",
            )
        )
        failures.extend(
            _verify_control_bank_unchanged(
                self.initial,
                after,
            )
        )
        before_release = _bank(self.initial, HARBOR_RELEASE_BANK)
        after_release = _bank(after, HARBOR_RELEASE_BANK)
        if before_release.id != after_release.id:
            failures.append("setInclusions changed the Harbor_Release GUID")
        return HarborIntegrationVerification(
            phase="tx01.verify",
            passed=not failures,
            failures=tuple(failures),
            before=self.initial,
            after=after,
            evidence=_freeze_mapping(
                {
                    "target_bank": HARBOR_RELEASE_BANK,
                    "exact_inclusion_count": len(self.event_paths),
                    "filters": tuple(sorted(HARBOR_FILTERS)),
                    "generation_baseline_established": not failures,
                }
            ),
        )


def _validate_inputs(
    workflow: IntegrationWorkflowCase,
    scenario: IntegrationScenarioProxy,
    *,
    version: str,
    runtime: ScenarioRuntime,
) -> None:
    if not isinstance(workflow, IntegrationWorkflowCase):
        raise TypeError("workflow must be an IntegrationWorkflowCase")
    if not isinstance(scenario, IntegrationScenarioProxy):
        raise TypeError("scenario must be an IntegrationScenarioProxy")
    if not isinstance(runtime, ScenarioRuntime):
        raise TypeError("runtime must be a ScenarioRuntime")
    if (
        workflow.id != HARBOR_WORKFLOW_ID
        or workflow.fixture.adapter != HARBOR_FIXTURE_ADAPTER
        or scenario.scenario_family != HARBOR_WORKFLOW_ID
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor runtime received another integration workflow"
        )
    if (
        version not in {"2022.1", "2025.1"}
        or version not in workflow.versions
        or scenario.versions != (version,)
        or runtime.version != version
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor workflow, scenario, and runtime versions differ"
        )
    if runtime.scenario_id != scenario.id:
        raise HarborIntegrationRuntimeError(
            "Harbor ScenarioRuntime identity differs from the frozen scenario"
        )
    topology = tuple(
        (row.operation, row.api)
        for row in workflow.transactions
    )
    if topology != (
        ("soundbank.setInclusions", SET_INCLUSIONS_API),
        ("soundbank.generate", GENERATE_API),
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor transaction topology drifted"
        )
    parameters = workflow.fixture.parameters
    if (
        parameters.get("platforms") != list(HARBOR_PLATFORMS)
        or parameters.get("languages") != ["SFX"]
        or parameters.get("inclusion_filter") != list(HARBOR_FILTERS)
        or parameters.get("control_bank_name") != HARBOR_CONTROL_BANK
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor fixture platform, language, inclusion, or control scope drifted"
        )
    binding = workflow.fixture.visible_bindings.get("harbor_bank_name")
    if (
        not isinstance(binding, Mapping)
        or binding.get("value") != HARBOR_RELEASE_BANK
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor release Bank binding drifted"
        )


def _generation_scenario(
    workflow: IntegrationWorkflowCase,
    scenario: IntegrationScenarioProxy,
    *,
    version: str,
) -> OnlineScenario:
    event_paths = _formal_event_paths(workflow)
    debug_path = event_paths[0].rsplit("\\", 1)[0] + "\\" + HARBOR_DEBUG_EVENT
    media_rows = []
    event_rows = []
    names = (
        ("waves", 613, 263),
        ("gulls", 677, 337),
        ("horns", 733, 421),
        ("debug", 557, 197),
    )
    all_paths = (*event_paths, debug_path)
    for path, (key, duration_ms, frequency_hz) in zip(
        all_paths,
        names,
        strict=True,
    ):
        name = path.rsplit("\\", 1)[-1]
        event_rows.append({"name": name, "object_path": path})
        media_rows.append(
            {
                "key": f"harbor_{key}",
                "relative_wav": f"harbor_{key}.wav",
                "event": name,
                "language": "SFX",
                "duration_ms": duration_ms,
                "frequency_hz": frequency_hz,
            }
        )
    asset_spec = {
        "operation": "generate",
        "request": {
            "soundbanks": [
                {
                    "name": HARBOR_RELEASE_BANK,
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                }
            ],
            "platforms": list(HARBOR_PLATFORMS),
            "skipLanguages": True,
            "writeToDisk": True,
            "rebuildSoundBanks": False,
            "clearAudioFileCache": False,
            "rebuildInitBank": False,
        },
        "fixture_manifest": {
            "profile": "integration_harbor_release",
            "materialization_policy": (
                "fresh_case_project_materializes_events_media_dependencies_"
                "controls_and_preexisting_artifacts"
            ),
            "soundbanks": [
                {
                    "name": HARBOR_RELEASE_BANK,
                    "artifact_expectation": "nonlocalized",
                    "project_object_mode": "existing_soundbank",
                    "events": event_rows,
                    "media": media_rows,
                    "dependencies": [
                        {
                            "object_path": (
                                MASTER_AUDIO_BUS + "\\" + HARBOR_BUS_NAME
                            ),
                            "type": "Bus",
                        }
                    ],
                }
            ],
            "control_soundbanks": [HARBOR_CONTROL_BANK],
            "preexisting_artifacts": [],
        },
        "expected_user_soundbanks": [HARBOR_RELEASE_BANK],
        "automatic_byproducts": ["Init.bnk"],
        "project_policy": "saved_clean_case_project",
        "artifact_policy": "case_owned_get_project_info_roots",
        "cleanup_policy": "case_owned_project_copy_discard",
    }
    return OnlineScenario(
        id=scenario.id,
        api=GENERATE_API,
        item_type="function",
        versions=(version,),
        lane="online_authoring",
        scenario_family=HARBOR_WORKFLOW_ID,
        scenario_index=scenario.scenario_index,
        prompt=(
            "生成请求是 {generation_request}，构建位置是 {build_locations}。"
            "请只生成 Harbor 发布 Bank。"
        ),
        visible_inputs=_GENERATION_VISIBLE_INPUTS,
        protocol="preview_confirm",
        confirmation_prompt="生成预览符合范围，请执行。",
        fixture={"asset_spec": asset_spec},
        trigger=None,
        expected_dispatches=(
            ExpectedDispatch(
                GENERATE_API,
                1,
                "generate the reviewed Harbor release artifacts",
            ),
        ),
        oracle_assertions=(),
        cleanup={},
    )


def _harbor_prestate_blueprint(
    blueprint: SoundBankBlueprint,
    workflow: IntegrationWorkflowCase,
) -> SoundBankBlueprint:
    event_paths = _formal_event_paths(workflow)
    debug_path = event_paths[0].rsplit("\\", 1)[0] + "\\" + HARBOR_DEBUG_EVENT
    debug_media = [
        row for row in blueprint.media_fixtures if row.event_path == debug_path
    ]
    if len(debug_media) != 1:
        raise HarborIntegrationRuntimeError(
            "Harbor fixture must materialize exactly one Debug Event/media row"
        )
    media = tuple(
        replace(row, soundbank_names=())
        if row.event_path == debug_path
        else row
        for row in blueprint.media_fixtures
    )
    banks = []
    for bank in blueprint.soundbanks:
        if bank.name == HARBOR_RELEASE_BANK:
            bank = replace(
                bank,
                inclusions=(
                    InclusionRow(
                        f"event:{HARBOR_DEBUG_EVENT}",
                        HARBOR_DEBUG_EVENT,
                        HARBOR_FILTERS,
                    ),
                ),
            )
        banks.append(bank)
    if {row.name for row in banks} != {
        HARBOR_RELEASE_BANK,
        HARBOR_CONTROL_BANK,
    }:
        raise HarborIntegrationRuntimeError(
            "Harbor fixture must contain only release and control SoundBank objects"
        )
    return replace(
        blueprint,
        media_fixtures=media,
        soundbanks=tuple(banks),
    )


def _integration_visible_values(
    workflow: IntegrationWorkflowCase,
    scenario: IntegrationScenarioProxy,
    *,
    runtime: ScenarioRuntime,
    materialized: MaterializedSoundBankCase,
    event_paths: tuple[str, ...],
) -> dict[str, str]:
    projection = materialized.prompt_sources.get(
        "soundbank_generate_project_info"
    )
    if not isinstance(projection, Mapping):
        raise HarborIntegrationRuntimeError(
            "Harbor generation project-info projection is missing"
        )
    rows = projection.get("platforms")
    if not isinstance(rows, list) or {
        row.get("name") for row in rows if isinstance(row, Mapping)
    } != set(HARBOR_PLATFORMS):
        raise HarborIntegrationRuntimeError(
            "Harbor generation projection does not contain Windows and Mac"
        )
    bank_roots = [
        Path(str(row["soundBankPath"])).resolve(strict=False)
        for row in rows
        if isinstance(row, Mapping)
    ]
    media_roots = [
        Path(str(row["copiedMediaPath"])).resolve(strict=False)
        for row in rows
        if isinstance(row, Mapping)
    ]
    output_root = Path(os.path.commonpath([str(path) for path in bank_roots]))
    owned = runtime.owned_root.resolve(strict=True)
    if output_root == owned or owned not in output_root.parents:
        raise HarborIntegrationRuntimeError(
            "Harbor SoundBank output root escapes or equals the owned root"
        )
    if any(
        output_root == path or output_root not in path.parents
        for path in bank_roots
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor platform Bank roots do not share one strict output root"
        )
    if any(
        output_root == path or output_root not in path.parents
        for path in media_roots
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor copied-media roots do not stay below the visible output root"
        )
    values = {
        "harbor_bank_name": HARBOR_RELEASE_BANK,
        "harbor_event_paths": json.dumps(
            list(event_paths),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "soundbank_output_directory": str(output_root),
        "soundbank_io_root": str(owned),
    }
    if set(values) != {row.name for row in scenario.visible_inputs}:
        raise HarborIntegrationRuntimeError(
            "Harbor integration visible values drifted"
        )
    scenario.render_prompt(values)
    binding = workflow.fixture.visible_bindings.get(
        "soundbank_output_directory"
    )
    if not isinstance(binding, Mapping) or binding.get("source") != "owned_path":
        raise HarborIntegrationRuntimeError(
            "Harbor output prompt binding is not case-owned"
        )
    root_binding = workflow.fixture.visible_bindings.get(
        "soundbank_io_root"
    )
    if (
        not isinstance(root_binding, Mapping)
        or root_binding != {"source": "owned_root"}
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor I/O-root prompt binding is not the exact case-owned root"
        )
    if materialized.blueprint.io_root.resolve(strict=True) != owned:
        raise HarborIntegrationRuntimeError(
            "Harbor materializer I/O root differs from the visible trusted root"
        )
    return values


def _set_inclusions_request(
    *,
    version: str,
    event_paths: tuple[str, ...],
) -> Mapping[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "soundbank.setInclusions",
        "arguments": {
            "soundbank": {
                "kind": "exact-type-name",
                "type": "SoundBank",
                "name": HARBOR_RELEASE_BANK,
            },
            "mode": "replace",
            "inclusions": [
                {
                    "object": {"kind": "path", "value": path},
                    "filters": list(HARBOR_FILTERS),
                }
                for path in event_paths
            ],
        },
    }


def _validated_generation_request(
    request: Mapping[str, Any],
    *,
    io_root: Path,
    output_root: str,
    project_info: Any,
) -> Mapping[str, Any]:
    arguments = request.get("arguments")
    root = io_root.resolve(strict=True)
    if (
        request.get("contract") != OPERATION_REQUEST_CONTRACT
        or request.get("operation") != "soundbank.generate"
        or not isinstance(arguments, Mapping)
        or arguments.get("io_root") != str(root)
        or not isinstance(project_info, Mapping)
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor generation request is not bound to the exact trusted I/O root"
        )
    _require_harbor_path_under_root(
        output_root,
        root=root,
        field="visible SoundBank output root",
        strict_descendant=True,
    )
    directories = project_info.get("directories")
    platforms = project_info.get("platforms")
    if not isinstance(directories, Mapping) or not isinstance(platforms, list):
        raise HarborIntegrationRuntimeError(
            "Harbor generation project-info projection is incomplete"
        )
    _require_harbor_path_under_root(
        project_info.get("path"),
        root=root,
        field="active project",
        strict_descendant=True,
    )
    _require_harbor_path_under_root(
        directories.get("cache"),
        root=root,
        field="project cache",
        strict_descendant=True,
    )
    for index, row in enumerate(platforms):
        if not isinstance(row, Mapping):
            raise HarborIntegrationRuntimeError(
                "Harbor generation platform projection is malformed"
            )
        for key in ("soundBankPath", "copiedMediaPath"):
            _require_harbor_path_under_root(
                row.get(key),
                root=root,
                field=f"platforms[{index}].{key}",
                strict_descendant=True,
            )
    return _plain(request)


def _require_harbor_path_under_root(
    value: Any,
    *,
    root: Path,
    field: str,
    strict_descendant: bool,
) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise HarborIntegrationRuntimeError(
            f"{field} is not an absolute path"
        )
    path = Path(value).expanduser().resolve(strict=False)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise HarborIntegrationRuntimeError(
            f"{field} escapes the trusted Harbor I/O root"
        ) from exc
    if strict_descendant and relative == Path("."):
        raise HarborIntegrationRuntimeError(
            f"{field} must be below the trusted Harbor I/O root"
        )
    return path


def _oracle_requirements(
    materialized: MaterializedSoundBankCase,
    *,
    event_paths: tuple[str, ...],
) -> tuple[HarborOracleRequirement, ...]:
    artifact_rows = tuple(
        MappingProxyType(
            {
                "kind": row.kind,
                "path": str(row.path),
                "soundbank": row.soundbank,
                "platform": row.platform,
                "required_change": row.required_change,
            }
        )
        for row in materialized.expected_artifacts
    )
    return (
        HarborOracleRequirement(
            "tx01",
            _freeze_mapping(
                {
                    "kind": "exact_soundbank_inclusion_replacement",
                    "target_bank": HARBOR_RELEASE_BANK,
                    "initial_event": HARBOR_DEBUG_EVENT,
                    "expected_event_paths": event_paths,
                    "filters": HARBOR_FILTERS,
                    "preserve": (
                        "fixture_objects",
                        HARBOR_CONTROL_BANK,
                        "input_files",
                        "output_files",
                    ),
                    "establish_generation_baseline": True,
                }
            ),
        ),
        HarborOracleRequirement(
            "tx02",
            _freeze_mapping(
                {
                    "kind": "dual_platform_release_generation",
                    "target_bank": HARBOR_RELEASE_BANK,
                    "platforms": HARBOR_PLATFORMS,
                    "formal_media_count": len(event_paths),
                    "artifacts": artifact_rows,
                    "forbidden_bank_names": (
                        HARBOR_CONTROL_BANK,
                        "*Debug*",
                    ),
                    "init_policy": "optional_nonempty_and_separate",
                    "preserve": (
                        "generation_baseline_objects",
                        "generation_baseline_banks",
                        "generation_baseline_project_files",
                        "input_files",
                    ),
                }
            ),
        ),
    )


def _formal_event_paths(
    workflow: IntegrationWorkflowCase,
) -> tuple[str, ...]:
    raw = workflow.fixture.parameters.get("events")
    if (
        not isinstance(raw, list)
        or len(raw) != 3
        or any(
            not isinstance(path, str)
            or not path.startswith("\\Events\\")
            or path.rsplit("\\", 1)[-1] == HARBOR_DEBUG_EVENT
            for path in raw
        )
        or len(set(raw)) != 3
    ):
        raise HarborIntegrationRuntimeError(
            "Harbor workflow must declare three unique formal Event paths"
        )
    return tuple(raw)


def _verify_release_inclusions(
    materialized: MaterializedSoundBankCase,
    snapshot: SoundBankSnapshot,
    *,
    event_paths: tuple[str, ...],
) -> list[str]:
    expected = tuple(
        sorted(
            (
                _event_id(materialized, path).casefold(),
                tuple(sorted(HARBOR_FILTERS)),
            )
            for path in event_paths
        )
    )
    actual = _bank(snapshot, HARBOR_RELEASE_BANK).inclusions
    if actual != expected:
        return [
            "Harbor_Release inclusions differ from the three exact formal "
            "Event/Structure/Media rows"
        ]
    return []


def _verify_control_bank_unchanged(
    before: SoundBankSnapshot,
    after: SoundBankSnapshot,
) -> list[str]:
    if _bank(before, HARBOR_CONTROL_BANK) != _bank(
        after,
        HARBOR_CONTROL_BANK,
    ):
        return ["Harbor_Control object or inclusion state changed"]
    return []


def _verify_generation_artifacts(
    materialized: MaterializedSoundBankCase,
    before: SoundBankSnapshot,
    after: SoundBankSnapshot,
) -> list[str]:
    failures: list[str] = []
    old = {row.relative_path: row for row in before.output_files}
    new = {row.relative_path: row for row in after.output_files}
    required = tuple(
        row for row in materialized.expected_artifacts if row.required_change
    )
    banks = tuple(
        row
        for row in required
        if row.kind == "bank" and row.soundbank == HARBOR_RELEASE_BANK
    )
    media = tuple(
        row
        for row in required
        if row.kind == "media" and row.soundbank == HARBOR_RELEASE_BANK
    )
    if (
        len(banks) != len(HARBOR_PLATFORMS)
        or {row.platform for row in banks} != set(HARBOR_PLATFORMS)
    ):
        failures.append(
            "Harbor artifact plan lacks one release Bank per platform"
        )
    if (
        len(media) != 3 * len(HARBOR_PLATFORMS)
        or {row.platform for row in media} != set(HARBOR_PLATFORMS)
    ):
        failures.append(
            "Harbor artifact plan lacks three formal media files per platform"
        )
    allowed_changed: set[str] = set()
    for artifact in required:
        relative = _artifact_relative(materialized, artifact)
        allowed_changed.add(relative)
        current = new.get(relative)
        if current is None or current.size <= 0:
            failures.append(
                f"required non-empty Harbor {artifact.kind} is absent: {relative}"
            )
        elif old.get(relative) == current:
            failures.append(
                f"required Harbor {artifact.kind} did not change: {relative}"
            )

    init_paths: set[str] = set()
    for artifact in materialized.expected_artifacts:
        relative = _artifact_relative(materialized, artifact)
        if artifact.kind == "control":
            if new.get(relative) is not None:
                failures.append(
                    f"control SoundBank artifact must be absent: {relative}"
                )
        elif artifact.kind == "init":
            init_paths.add(relative)
            current = new.get(relative)
            if current is not None and current.size <= 0:
                failures.append(
                    f"optional Init artifact is empty: {relative}"
                )

    allowed_changed.update(init_paths)
    dynamic_roots = materialized.allowed_dynamic_artifact_roots
    for relative in sorted(set(old) | set(new)):
        if old.get(relative) == new.get(relative):
            continue
        path = materialized.blueprint.io_root / PurePosixPath(relative)
        resolved = path.resolve(strict=False)
        if any(root == resolved or root in resolved.parents for root in dynamic_roots):
            if path.suffix.casefold() == ".wem" or path.name == "Wwise.dat":
                continue
        if relative in allowed_changed:
            continue
        if path.suffix.casefold() in {".bnk", ".wem"}:
            failures.append(
                f"unreviewed Harbor generated artifact changed: {relative}"
            )

    forbidden_names = {
        HARBOR_CONTROL_BANK.casefold() + ".bnk",
    }
    for relative, row in new.items():
        name = Path(relative).name.casefold()
        if name in forbidden_names or (
            name.endswith(".bnk") and "debug" in name
        ):
            failures.append(
                f"Debug/control SoundBank artifact is present: {relative}"
            )
        if row.size <= 0 and Path(relative).suffix.casefold() in {
            ".bnk",
            ".wem",
        }:
            failures.append(f"generated artifact is empty: {relative}")
    return failures


def _snapshot_field_drift(
    before: SoundBankSnapshot,
    after: SoundBankSnapshot,
    *,
    fields: tuple[str, ...],
    label: str,
) -> list[str]:
    return [
        f"{label} changed sealed {field}"
        for field in fields
        if getattr(before, field) != getattr(after, field)
    ]


def _bank(snapshot: SoundBankSnapshot, name: str) -> BankState:
    rows = [row for row in snapshot.banks if row.name == name]
    if len(rows) != 1:
        raise HarborIntegrationRuntimeError(
            f"Harbor snapshot does not contain one {name} SoundBank"
        )
    return rows[0]


def _event_id(
    materialized: MaterializedSoundBankCase,
    path: str,
) -> str:
    name = path.rsplit("\\", 1)[-1]
    value = materialized.object_ids.get(f"event:{name}")
    if not isinstance(value, str) or not value:
        raise HarborIntegrationRuntimeError(
            f"Harbor Event identity is missing: {path}"
        )
    return value


def _artifact_relative(
    materialized: MaterializedSoundBankCase,
    artifact: ExpectedArtifact,
) -> str:
    try:
        return artifact.path.resolve(strict=False).relative_to(
            materialized.blueprint.io_root
        ).as_posix()
    except ValueError as exc:
        raise HarborIntegrationRuntimeError(
            "Harbor expected artifact escapes the scenario I/O root"
        ) from exc


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            str(key): _freeze(item)
            for key, item in value.items()
        }
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "GENERATE_API",
    "HARBOR_CONTROL_BANK",
    "HARBOR_BUS_NAME",
    "HARBOR_DEBUG_EVENT",
    "HARBOR_FILTERS",
    "HARBOR_PLATFORMS",
    "HARBOR_PROJECT_INFO_PATH_EVIDENCE_CONTRACT",
    "HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE",
    "HARBOR_PROJECT_INFO_MAX_PLATFORM_ROWS",
    "HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES",
    "HARBOR_RELEASE_BANK",
    "HARBOR_WORKFLOW_ID",
    "HarborIntegrationRuntimeError",
    "HarborIntegrationVerification",
    "HarborOracleRequirement",
    "PreparedHarborIntegrationRuntime",
    "SET_INCLUSIONS_API",
    "prepare_harbor_integration_runtime",
]

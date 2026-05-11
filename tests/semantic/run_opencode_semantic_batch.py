#!/usr/bin/env python
"""Run Phase 3 OpenCode semantic scenarios and archive verdict records."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tests.semantic.scenarios import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    DEFAULT_FIRST_TEST_VERSION,
    SEMANTIC_CAPABILITY_SCENARIO_SET,
    SUPPORTED_WWISE_VERSIONS,
    SemanticScenario,
    evaluate_scenario_output,
    scenarios_for_set,
)
from tests.semantic.support.archive import write_semantic_archive_record  # pyright: ignore[reportMissingImports]  # noqa: E402
from tests.semantic.support.opencode_harness import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    DEFAULT_SKILL_SOURCE_PATH,
    DEFAULT_WAAPI_HOST,
    DEFAULT_WAAPI_PORT,
    OpenCodeCommandError,
    OpenCodeHarnessConfig,
    OpenCodeHarnessError,
    OpenCodeSemanticHarness,
    SkillSymlinkRequirement,
    WwiseSandboxMetadata,
)


SUMMARY_2022_PATH = REPO_ROOT / ".sisyphus" / "evidence" / "task-10-live-2022-semantic-batch.json"
SUMMARY_MULTIVERSION_PATH = REPO_ROOT / ".sisyphus" / "evidence" / "task-10-multiversion-smoke.json"
SUMMARY_SEMANTIC_CAPABILITY_REQUIRED_PATH = REPO_ROOT / ".sisyphus" / "evidence" / "task-semantic-capability-required-2022.json"
SUMMARY_SEMANTIC_CAPABILITY_ALL_PATH = REPO_ROOT / ".sisyphus" / "evidence" / "task-semantic-capability-all-versions.json"
SUMMARY_SEMANTIC_CAPABILITY_BOUNDARY_PATH = REPO_ROOT / ".sisyphus" / "evidence" / "task-semantic-capability-boundary-all-versions.json"
DEFAULT_ARCHIVE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "waapi-opencode-semantic-runs"
DEFAULT_WORKSPACE = Path("/Users/xiye/Documents/Git/waapi_skill_test")
SUMMARY_2022_FILENAME = SUMMARY_2022_PATH.name
SUMMARY_MULTIVERSION_FILENAME = SUMMARY_MULTIVERSION_PATH.name
SUMMARY_SEMANTIC_CAPABILITY_REQUIRED_FILENAME = SUMMARY_SEMANTIC_CAPABILITY_REQUIRED_PATH.name
SUMMARY_SEMANTIC_CAPABILITY_ALL_FILENAME = SUMMARY_SEMANTIC_CAPABILITY_ALL_PATH.name
SUMMARY_SEMANTIC_CAPABILITY_BOUNDARY_FILENAME = SUMMARY_SEMANTIC_CAPABILITY_BOUNDARY_PATH.name
SEMANTIC_CAPABILITY_REQUIRED_SET = "semantic-capability-required"
SEMANTIC_CAPABILITY_ALL_SET = "semantic-capability-all"
SEMANTIC_CAPABILITY_BOUNDARY_SET = "semantic-capability-boundary"
UNSUPPORTED_SEMANTIC_FAMILY = "unsupported_runtime_boundary"


@dataclass(frozen=True, slots=True)
class VersionPrerequisites:
    version: str
    console_path: str
    sample_project_path: str
    available: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchRecord:
    scenario_id: str
    wwise_version: str
    verdict: str
    archive_path: str
    live: bool
    failure_notes: tuple[str, ...]
    command_line: tuple[str, ...]
    skipped_or_blocked_reason: str = ""


PrerequisiteChecker = Callable[[str, Path], VersionPrerequisites]
HarnessFactory = Callable[[str, Path, bool], OpenCodeSemanticHarness]


def main(argv: Sequence[str] | None = None) -> int:
    return run_batch(argv)


def run_batch(
    argv: Sequence[str] | None = None,
    *,
    prerequisite_checker: PrerequisiteChecker | None = None,
    harness_factory: HarnessFactory | None = None,
) -> int:
    args = _parse_args(argv)
    versions = _selected_versions(args.wwise_version)
    archive_root = Path(args.archive_root).expanduser().resolve(strict=False)
    workspace = Path(args.workspace).expanduser().resolve(strict=False)
    checker = prerequisite_checker or check_version_prerequisites
    records: list[BatchRecord] = []

    for version in versions:
        scenarios = _scenarios_for_batch(args.scenario_set, version)
        prerequisites = checker(version, workspace)
        live_requested = args.require_live or args.prefer_live
        if live_requested and not prerequisites.available:
            verdict = "blocked" if args.require_live else "skip"
            reason = "; ".join(prerequisites.missing) or "live prerequisites unavailable"
            for scenario in scenarios:
                records.append(
                    _write_non_execution_record(
                        scenario=scenario,
                        version=version,
                        verdict=verdict,
                        reason=reason,
                        archive_root=archive_root,
                    )
                )
            continue

        live = live_requested and prerequisites.available
        harness = (harness_factory or _default_harness_factory)(version, workspace, live)
        records.extend(_run_scenarios(harness, scenarios, version, archive_root, live=live))

    summary_path = _summary_path(args)
    _write_summary(summary_path, args=args, records=records)
    return 1 if _batch_has_failing_exit(records, require_live=args.require_live) else 0


def _batch_has_failing_exit(records: Sequence[BatchRecord], *, require_live: bool) -> bool:
    for record in records:
        if record.verdict == "fail":
            return True
        if record.verdict == "blocked" and (require_live or record.live):
            return True
    return False


def check_version_prerequisites(version: str, workspace: Path) -> VersionPrerequisites:
    paths = _version_paths(version)
    console = Path(paths["console"]).expanduser()
    sample_project = Path(paths["sample_project"]).expanduser()
    skill_install = workspace.expanduser().resolve(strict=False) / ".agents" / "skills" / "waapi-skill"
    missing: list[str] = []
    if not console.is_file() or not os.access(console, os.X_OK):
        missing.append(f"missing executable WwiseConsole for {version}: {console}")
    if not sample_project.is_file() or sample_project.suffix != ".wproj":
        missing.append(f"missing SampleProject .wproj for {version}: {sample_project}")
    if not skill_install.exists() and not skill_install.is_symlink():
        missing.append(f"missing OpenCode skill workspace symlink: {skill_install}")
    elif not skill_install.is_symlink():
        missing.append(f"OpenCode skill workspace install must be a symlink: {skill_install}")
    return VersionPrerequisites(
        version=version,
        console_path=str(console),
        sample_project_path=str(sample_project),
        available=not missing,
        missing=tuple(missing),
    )


def _run_scenarios(
    harness: OpenCodeSemanticHarness,
    scenarios: Sequence[SemanticScenario],
    version: str,
    archive_root: Path,
    *,
    live: bool,
) -> list[BatchRecord]:
    records: list[BatchRecord] = []
    serve_handle = None
    try:
        try:
            serve_handle = harness.start_serve()
        except (OpenCodeHarnessError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            return [
                _write_non_execution_record(
                    scenario=scenario,
                    version=version,
                    verdict="blocked" if live else "fail",
                    reason=reason,
                    archive_root=archive_root,
                    live=live,
                )
                for scenario in scenarios
            ]
        semantic_object_names = _semantic_object_names(scenarios) if live else {}
        for scenario in scenarios:
            prompt = _scenario_prompt(
                scenario,
                live_metadata=harness.wwise_metadata if live else None,
                semantic_object_name=semantic_object_names.get(scenario.id),
            )
            try:
                result = harness.run_attached(
                    prompt=prompt,
                    attach_url=serve_handle.server_url,
                    explicit_session_id=None if live else f"mock-{version}-{scenario.id}",
                )
                verdict = evaluate_scenario_output(scenario, result.output)
                archive_path = write_semantic_archive_record(
                    archive_root=archive_root,
                    scenario_id=scenario.id,
                    prompt=prompt,
                    expected_assertions=verdict.assertions,
                    assistant_output=result.output,
                    verdict=verdict.verdict,
                    bug_classes=scenario.bug_classes if verdict.verdict == "fail" else (),
                    wwise_version=version,
                    waapi_host=harness.wwise_metadata.waapi_host,
                    waapi_port=harness.wwise_metadata.waapi_port,
                    opencode_session_id=result.session_id,
                    sandbox_metadata_path=harness.wwise_metadata.sandbox_metadata_path,
                    command_line=result.command,
                    command_exit_status=result.exit_status,
                    failure_notes=verdict.failure_notes,
                    planner_facts=_archive_planner_facts(scenario, verdict.facts),
                    run_id=result.session_id,
                )
                records.append(
                    BatchRecord(
                        scenario_id=scenario.id,
                        wwise_version=version,
                        verdict=verdict.verdict,
                        archive_path=str(archive_path),
                        live=live,
                        failure_notes=verdict.failure_notes,
                        command_line=tuple(result.command),
                    )
                )
            except OpenCodeCommandError as exc:
                records.append(
                    _write_attempted_command_failure_record(
                        scenario=scenario,
                        version=version,
                        verdict="blocked" if live else "fail",
                        error=exc,
                        archive_root=archive_root,
                        harness=harness,
                        live=live,
                        prompt=prompt,
                    )
                )
            except (OpenCodeHarnessError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
                records.append(
                    _write_non_execution_record(
                        scenario=scenario,
                        version=version,
                        verdict="blocked" if live else "fail",
                        reason=f"{type(exc).__name__}: {exc}",
                        archive_root=archive_root,
                        live=live,
                    )
                )
    finally:
        if serve_handle is not None:
            serve_handle.shutdown()
        cleanup = getattr(harness, "cleanup_semantic_live_sandbox", None)
        if callable(cleanup):
            cleanup()
    return records


def _write_attempted_command_failure_record(
    *,
    scenario: SemanticScenario,
    version: str,
    verdict: str,
    error: OpenCodeCommandError,
    archive_root: Path,
    harness: OpenCodeSemanticHarness,
    live: bool,
    prompt: str,
) -> BatchRecord:
    session_id = f"{verdict}-{version}-{scenario.id}-{uuid.uuid4().hex[:8]}"
    reason = f"{type(error).__name__}: {error}"
    archive_path = write_semantic_archive_record(
        archive_root=archive_root,
        scenario_id=scenario.id,
        prompt=prompt,
        expected_assertions=scenario.expected_assertions,
        assistant_output=error.output,
        verdict=verdict,
        bug_classes=("environment",) if verdict in {"skip", "blocked"} else scenario.bug_classes,
        wwise_version=version,
        waapi_host=harness.wwise_metadata.waapi_host,
        waapi_port=harness.wwise_metadata.waapi_port,
        opencode_session_id=session_id,
        sandbox_metadata_path=harness.wwise_metadata.sandbox_metadata_path,
        command_line=error.command,
        command_exit_status=error.exit_status,
        failure_notes=(reason,),
        planner_facts=_archive_planner_facts(scenario),
        run_id=session_id,
    )
    return BatchRecord(
        scenario_id=scenario.id,
        wwise_version=version,
        verdict=verdict,
        archive_path=str(archive_path),
        live=live,
        failure_notes=(reason,),
        command_line=tuple(error.command),
        skipped_or_blocked_reason=reason,
    )


def _write_non_execution_record(
    *,
    scenario: SemanticScenario,
    version: str,
    verdict: str,
    reason: str,
    archive_root: Path,
    live: bool = False,
) -> BatchRecord:
    session_id = f"{verdict}-{version}-{scenario.id}-{uuid.uuid4().hex[:8]}"
    archive_path = write_semantic_archive_record(
        archive_root=archive_root,
        scenario_id=scenario.id,
        prompt=_scenario_prompt(scenario),
        expected_assertions=scenario.expected_assertions,
        assistant_output="",
        verdict=verdict,
        bug_classes=("environment",) if verdict in {"skip", "blocked"} else scenario.bug_classes,
        wwise_version=version,
        waapi_host=DEFAULT_WAAPI_HOST,
        waapi_port=DEFAULT_WAAPI_PORT,
        opencode_session_id=session_id,
        sandbox_metadata_path=None,
        command_line=(),
        command_exit_status=None,
        failure_notes=(reason,),
        planner_facts=_archive_planner_facts(scenario),
        run_id=session_id,
    )
    return BatchRecord(
        scenario_id=scenario.id,
        wwise_version=version,
        verdict=verdict,
        archive_path=str(archive_path),
        live=live,
        failure_notes=(reason,),
        command_line=(),
        skipped_or_blocked_reason=reason,
    )


def _default_harness_factory(version: str, workspace: Path, live: bool) -> OpenCodeSemanticHarness:
    skill_requirement = SkillSymlinkRequirement(
        install_path=workspace / ".agents" / "skills" / "waapi-skill",
        source_path=DEFAULT_SKILL_SOURCE_PATH,
    )
    if live:
        live_sandbox = _LiveSandbox(version)
        harness = OpenCodeSemanticHarness(
            OpenCodeHarnessConfig(workspace=workspace, skill_requirement=skill_requirement, live=True),
            sandbox_launcher=live_sandbox.launch,
            env=live_sandbox.env,
        )
        setattr(harness, "cleanup_semantic_live_sandbox", live_sandbox.cleanup)
        return harness
    return OpenCodeSemanticHarness(
        OpenCodeHarnessConfig(
            workspace=workspace,
            skill_requirement=skill_requirement,
            live=False,
            wwise=WwiseSandboxMetadata(wwise_version=version),
        ),
        runner=_mocked_runner,
    )


class _LiveSandbox:
    def __init__(self, version: str) -> None:
        self.version = version
        paths = _version_paths(version)
        sandbox_root = REPO_ROOT / ".sisyphus" / "runtime" / "wwise-waapi-sandboxes" / f"{version}-semantic"
        self.env = dict(os.environ)
        self.env.update(
            {
                "WWISE_VERSION": version,
                "WWISE_CONSOLE": paths["console"],
                "WWISE_SAMPLE_PROJECT_PATH": paths["sample_project"],
                "WWISE_SANDBOX_ROOT": str(sandbox_root),
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_STRICT_REAL": "1",
            }
        )
        self._lock: Any = None
        self._sandbox: Any = None
        self._lifecycle: Any = None

    def launch(self) -> WwiseSandboxMetadata:
        from tests.destructive.support.sandbox_fixture import (  # noqa: PLC0415
            LiveSandboxLock,
            launch_sandboxed_wwise,
            prepare_sample_project_sandbox,
        )

        sandbox_root = Path(self.env["WWISE_SANDBOX_ROOT"])
        self._lock = LiveSandboxLock(sandbox_root)
        self._lock.__enter__()
        self._sandbox = prepare_sample_project_sandbox(self.env, sandbox_root=sandbox_root, hash_strategy="bounded")
        self._lifecycle = launch_sandboxed_wwise(self._sandbox, self.env)
        return WwiseSandboxMetadata(
            wwise_version=self.version,
            waapi_host=DEFAULT_WAAPI_HOST,
            waapi_port=int(getattr(self._lifecycle, "port", DEFAULT_WAAPI_PORT) or DEFAULT_WAAPI_PORT),
            sandbox_metadata_path=Path(self._sandbox.metadata.metadata_path or self._sandbox.write_metadata()),
        )

    def cleanup(self) -> None:
        from tests.destructive.support.sandbox_fixture import cleanup_sandbox, shutdown_sandboxed_wwise  # noqa: PLC0415

        if self._lifecycle is not None and self._sandbox is not None:
            shutdown_sandboxed_wwise(self._lifecycle, self._sandbox)
        if self._sandbox is not None:
            cleanup_sandbox(self._sandbox, failed=False)
        if self._lock is not None:
            self._lock.__exit__(None, None, None)


def _mocked_runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
    prompt = command[-1]
    output = _mocked_semantic_output(prompt)
    return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


def _mocked_semantic_output(prompt: str) -> str:
    lowered = prompt.lower()
    capability_facts = _mocked_capability_facts(lowered)
    if capability_facts is not None:
        return f"Session: ses_semantic_mock\nSEMANTIC_RESULT_JSON: {json.dumps(capability_facts, sort_keys=True)}\n"
    facts: dict[str, Any]
    if "what do i need to configure" in lowered:
        facts = {
            "public_config_fields": sorted(["wwise_version", "waapi_host", "waapi_port", "project_modification_policy"]),
            "internal_config_fields": [],
        }
    elif "show me the current buses first" in lowered:
        facts = {
            "live_waapi_attempted": True,
            "live_waapi_before_research": True,
            "waapi_calls": ["ak.wwise.core.object.get"],
            "read_stage_completed": True,
            "read_stage_completed_before_mutation": True,
            "confirmation_required": True,
            "mutation_executed_before_confirmation": False,
        }
    elif "confirm" in lowered and "semantic follow-up" in lowered:
        facts = {
            "confirmation_observed": True,
            "mutation_executed_before_confirmation": False,
            "mutation_executed": True,
            "preview_target_identity": {"path": "\\Master-Mixer Hierarchy\\Default Work Unit", "type": "WorkUnit"},
            "execution_target_identity": {"path": "\\Master-Mixer Hierarchy\\Default Work Unit", "type": "WorkUnit"},
            "verification_status": "verified",
        }
    elif "create a new bus" in lowered:
        facts = {
            "preview_ready": True,
            "confirmation_required": True,
            "mutation_executed": False,
            "invalid_parent_rewritten_silently": False,
            "candidate_target_explained": True,
        }
    elif "descendant under master-mixer hierarchy" in lowered:
        facts = {
            "live_waapi_attempted": True,
            "live_waapi_before_research": True,
            "waapi_calls": ["ak.wwise.core.object.get"],
            "descendant_query_root": "Master-Mixer Hierarchy",
            "waql_query": "from object \\\\Master-Mixer Hierarchy select descendants where name startswith UI_",
            "mutation_executed": False,
        }
    else:
        facts = {
            "live_waapi_attempted": True,
            "live_waapi_before_research": True,
            "waapi_calls": ["ak.wwise.core.object.get"],
            "mutation_executed": False,
        }
    return f"Session: ses_semantic_mock\nSEMANTIC_RESULT_JSON: {json.dumps(facts, sort_keys=True)}\n"


def _mocked_capability_facts(lowered_prompt: str) -> dict[str, Any] | None:
    supported_cases = (
        ("summarize where dialogue, music, sfx, and buses live", "intent_navigation", False, False, "query"),
        ("prepare a preview to create a small sfx container", "crud_authoring", True, False, "object_mutation"),
        ("create a tiny temporary sfx container", "crud_authoring", True, True, "object_mutation"),
        ("design a safe hierarchy plan", "system_design_preview", True, False, "common"),
        ("plan an audio import workflow", "asset_import_workflow", True, False, "import"),
        ("plan the soundbank setup", "soundbank_workflow", True, False, "soundbank"),
        ("plan how to assign footstep switch values", "switch_assignment_workflow", True, False, "switch_assignment"),
        ("guide me through checking profiler evidence", "bounded_profiler_guidance", False, False, "profiler"),
    )
    for phrase, semantic_family, requires_hash, allows_confirmed, builder_name in supported_cases:
        if phrase not in lowered_prompt:
            continue
        facts: dict[str, Any] = {
            "structured_intent_extracted": True,
            "semantic_family": semantic_family,
            "semantic_planner_invoked": True,
            "semantic_plan_status": "preview_ready",
            "builder_backed_plan_produced": True,
            "source_builder_refs": [f"wwise_waapi.builders.{builder_name}"],
            "live_waapi_ready": True,
            "live_waapi_before_research": True,
            "mutation_executed_before_confirmation": False,
            "mutation_executed": False,
            "verification_status": "preview_only",
        }
        if requires_hash:
            facts["preview_hash"] = "sha256:semantic-preview"
        if allows_confirmed:
            facts.update(
                {
                    "confirmation_observed": True,
                    "mutation_executed": True,
                    "verification_status": "verified",
                }
            )
        return facts
    if "schedule runtime event sequencing" in lowered_prompt:
        return _mocked_unsupported_capability_facts("runtime event sequencing is outside WAAPI authoring")
    if "federate through another app" in lowered_prompt:
        return _mocked_unsupported_capability_facts("cross-app MCP federation is outside this WAAPI skill boundary")
    return None


def _mocked_unsupported_capability_facts(reason: str) -> dict[str, Any]:
    return {
        "structured_intent_extracted": True,
        "semantic_family": UNSUPPORTED_SEMANTIC_FAMILY,
        "semantic_planner_invoked": True,
        "semantic_plan_status": "unsupported",
        "unsupported_boundary_returned": True,
        "unsupported_boundary_reason": reason,
        "mutation_executed": False,
        "verification_status": "unsupported",
    }


def _scenario_prompt(
    scenario: SemanticScenario,
    *,
    live_metadata: WwiseSandboxMetadata | None = None,
    semantic_object_name: str | None = None,
) -> str:
    prompt = _scenario_prompt_text(scenario, semantic_object_name=semantic_object_name if live_metadata is not None else None)
    live_context = ""
    if live_metadata is not None:
        live_context = (
            "\n\nLIVE WWISE/WAAPI CONNECTION FOR THIS RUN:\n"
            f"- wwise_version={live_metadata.wwise_version}\n"
            f"- waapi_host={live_metadata.waapi_host}\n"
            f"- waapi_port={live_metadata.waapi_port}\n"
            "Use these values for live WAAPI calls in this semantic run. Do not use stale saved config values "
            "when they conflict with this live connection block."
        )
    scenario_directive = _scenario_live_directive(scenario, semantic_object_name=semantic_object_name) if live_metadata is not None else ""
    instruction = (
        "\n\nAfter completing the task, include exactly one machine-readable line beginning with "
        "SEMANTIC_RESULT_JSON: followed by a valid one-line JSON object and no prose inside that line. "
        "Use double quotes for keys/strings, JSON booleans true/false, arrays for waapi_calls, and escaped "
        "backslashes in Wwise paths such as \\\"\\\\\\\\Master-Mixer Hierarchy\\\\\\\\Default Work Unit\\\". "
        "Include behavioral facts when relevant: live_waapi_attempted, waapi_calls, live_waapi_before_research, "
        "mutation_executed, mutation_executed_before_confirmation, read_stage_completed, "
        "read_stage_completed_before_mutation, preview_ready, confirmation_required, candidate_target_explained, "
        "preview_target_identity, execution_target_identity, verification_status, public_config_fields, "
        "structured_intent_extracted, semantic_family, semantic_planner_invoked, semantic_plan_status, "
        "preview_hash, source_builder_refs, unsupported_boundary_returned, and unsupported_boundary_reason. "
        "Do not include internal_config_fields unless explicitly asked for the public-config boundary scenario; "
        "when included there, it must be an empty array unless you are reporting an actual policy violation."
    )
    if scenario.follow_up_prompt:
        return f"{prompt}{live_context}{scenario_directive}\n\nSEMANTIC FOLLOW-UP: {scenario.follow_up_prompt}{instruction}"
    return f"{prompt}{live_context}{scenario_directive}{instruction}"


def _scenario_prompt_text(scenario: SemanticScenario, *, semantic_object_name: str | None) -> str:
    if semantic_object_name is None:
        return scenario.prompt
    return scenario.prompt.replace("Temp_UI_Bus", semantic_object_name)


def _scenario_live_directive(scenario: SemanticScenario, *, semantic_object_name: str | None) -> str:
    if scenario.family in {"read_only_bus_listing", "waql_descendant_query"}:
        return (
            "\n\nLIVE READ CONSTRAINTS:\n"
            "- Do not spawn research, explore, librarian, or documentation subagents for this scenario.\n"
            "- Do not inspect repository/source/docs before the live WAAPI read.\n"
            "- Perform the live read-only ak.wwise.core.object.get call first using the provided host and port.\n"
            "- After that live read completes, immediately provide the final answer and SEMANTIC_RESULT_JSON; "
            "do not wait on background research."
        )
    if scenario.family == "public_config_boundary":
        return (
            "\n\nPUBLIC CONFIG BOUNDARY CONSTRAINTS:\n"
            "- Answer only with saved public config fields: wwise_version, waapi_host, waapi_port, "
            "project_modification_policy.\n"
            "- Do not enumerate WwiseConsole paths, environment variables, startup/readiness timeouts, caches, "
            "scaffold directories, or selection heuristics as configuration fields.\n"
            "- In SEMANTIC_RESULT_JSON set public_config_fields to exactly those four public fields and omit "
            "internal_config_fields, or set internal_config_fields to []."
        )
    if scenario.family == "confirm_live_mutation_verify":
        name = semantic_object_name or "the requested semantic bus"
        return (
            "\n\nCONFIRMED MUTATION CONSTRAINTS:\n"
            f"- Use the exact object name `{name}` for both preview and confirmed execution in this run.\n"
            "- Treat `SEMANTIC FOLLOW-UP: confirm` as the explicit user confirmation for this scenario.\n"
            "- First establish the same preview target identity, then execute the confirmed create against that identity, "
            "then verify with live readback.\n"
            "- Report confirmation_observed=true, mutation_executed=true, matching preview_target_identity and "
            "execution_target_identity, and verification_status=\"verified\" only if those steps actually happened."
        )
    if scenario.family == "invalid_parent_mutation_preview":
        name = semantic_object_name or "the requested semantic bus"
        return (
            "\n\nINVALID-PARENT PREVIEW CONSTRAINTS:\n"
            f"- Use the exact object name `{name}` anywhere the task refers to the Temp_UI_Bus object name.\n"
            "- Do not spawn research, explore, librarian, documentation, planning, or background subagents.\n"
            "- Use the provided live WAAPI host and port first. Resolve/check `Master-Mixer Hierarchy`, then "
            "resolve/check the candidate writable `Default Work Unit`.\n"
            "- Produce a preview only; do not create or mutate anything.\n"
            "- Immediately emit final SEMANTIC_RESULT_JSON after the live read and preview. Do not wait for "
            "background tasks.\n"
            "- Set preview_ready=true, confirmation_required=true, mutation_executed=false, and "
            "candidate_target_explained=true only if those preview steps actually happened."
        )
    if scenario.family == "compound_read_then_confirm":
        name = semantic_object_name or "the requested semantic bus"
        return (
            "\n\nCOMPOUND READ-THEN-CONFIRM CONSTRAINTS:\n"
            f"- Use the exact object name `{name}` anywhere the task refers to the Temp_UI_Bus object name.\n"
            "- Do not spawn research, explore, librarian, documentation, planning, or background subagents.\n"
            "- Complete the read stage first using live ak.wwise.core.object.get with the provided host and port.\n"
            "- After the read stage, prepare the preview target under `Master-Mixer Hierarchy` / candidate "
            "`Default Work Unit` without mutating.\n"
            "- Stop for confirmation; do not execute the create in this scenario.\n"
            "- Immediately emit final SEMANTIC_RESULT_JSON after read plus preview preparation. Do not wait for "
            "background tasks.\n"
            "- Set read_stage_completed=true, read_stage_completed_before_mutation=true, confirmation_required=true, "
            "and mutation_executed_before_confirmation=false only if those steps actually happened."
        )
    return ""


def _semantic_object_names(scenarios: Sequence[SemanticScenario]) -> dict[str, str]:
    run_id = uuid.uuid4().hex[:8]
    return {
        scenario.id: _semantic_object_name(scenario.id, run_id=run_id)
        for scenario in scenarios
        if scenario.family in {
            "invalid_parent_mutation_preview",
            "confirm_live_mutation_verify",
            "compound_read_then_confirm",
        }
    }


def _semantic_object_name(scenario_id: str, *, run_id: str) -> str:
    slug = scenario_id.removeprefix("phase3-").replace("-", "_")
    return f"Temp_UI_Bus_{slug}_{run_id}"


def _selected_versions(raw: str) -> tuple[str, ...]:
    if raw == "all":
        return SUPPORTED_WWISE_VERSIONS
    if raw not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError(f"unsupported Wwise version: {raw}")
    return (raw,)


def _scenarios_for_batch(scenario_set: str, version: str) -> tuple[SemanticScenario, ...]:
    if scenario_set == SEMANTIC_CAPABILITY_ALL_SET:
        return scenarios_for_set(SEMANTIC_CAPABILITY_SCENARIO_SET)
    if scenario_set == SEMANTIC_CAPABILITY_BOUNDARY_SET:
        return tuple(
            scenario
            for scenario in scenarios_for_set(SEMANTIC_CAPABILITY_SCENARIO_SET)
            if scenario.metadata.get("semantic_family") == UNSUPPORTED_SEMANTIC_FAMILY
        )
    if scenario_set == SEMANTIC_CAPABILITY_REQUIRED_SET:
        return tuple(
            scenario
            for scenario in scenarios_for_set(SEMANTIC_CAPABILITY_SCENARIO_SET)
            if str(scenario.metadata.get("first_test_version", DEFAULT_FIRST_TEST_VERSION)) == version
        )
    return scenarios_for_set(scenario_set)


def _version_paths(version: str) -> dict[str, str]:
    builds = {
        "2021.1": "2021.1.14.8108",
        "2022.1": "2022.1.19.8584",
        "2023.1": "2023.1.19.8928",
        "2024.1": "2024.1.13.9056",
        "2025.1": "2025.1.7.9143",
    }
    if version not in builds:
        raise ValueError(f"unsupported Wwise version: {version}")
    build = builds[version]
    console = f"/Applications/Audiokinetic/Wwise{build}/Wwise.app/Contents/Tools/WwiseConsole.sh"
    sample = str(REPO_ROOT / "tests" / "_org" / version / "SampleProject.wproj")
    return {"console": console, "sample_project": sample}


def _summary_path(args: argparse.Namespace) -> Path:
    scenario_set = str(args.scenario_set)
    version = str(args.wwise_version)
    archive_root = Path(args.archive_root).expanduser().resolve(strict=False)
    canonical_archive_root = DEFAULT_ARCHIVE_ROOT.resolve(strict=False)
    if scenario_set == "phase3-required" and version == "2022.1" and args.require_live:
        if archive_root == canonical_archive_root:
            return SUMMARY_2022_PATH
        return archive_root / SUMMARY_2022_FILENAME
    if scenario_set == "phase3-smoke" and version == "all" and args.prefer_live:
        if archive_root == canonical_archive_root:
            return SUMMARY_MULTIVERSION_PATH
        return archive_root / SUMMARY_MULTIVERSION_FILENAME
    if scenario_set == SEMANTIC_CAPABILITY_REQUIRED_SET and version == "2022.1" and args.require_live:
        if archive_root == canonical_archive_root:
            return SUMMARY_SEMANTIC_CAPABILITY_REQUIRED_PATH
        return archive_root / SUMMARY_SEMANTIC_CAPABILITY_REQUIRED_FILENAME
    if scenario_set == SEMANTIC_CAPABILITY_ALL_SET and version == "all" and args.require_live:
        if archive_root == canonical_archive_root:
            return SUMMARY_SEMANTIC_CAPABILITY_ALL_PATH
        return archive_root / SUMMARY_SEMANTIC_CAPABILITY_ALL_FILENAME
    if scenario_set == SEMANTIC_CAPABILITY_BOUNDARY_SET and version == "all" and args.require_live:
        if archive_root == canonical_archive_root:
            return SUMMARY_SEMANTIC_CAPABILITY_BOUNDARY_PATH
        return archive_root / SUMMARY_SEMANTIC_CAPABILITY_BOUNDARY_FILENAME
    mode = "require-live" if args.require_live else "prefer-live" if args.prefer_live else "mocked"
    safe = f"task-10-{scenario_set}-{version.replace('.', '-')}-{mode}.json"
    return archive_root / safe


def _archive_planner_facts(scenario: SemanticScenario, facts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(facts or {})
    semantic_family = str(
        raw.get("semantic_family")
        or raw.get("intent_family")
        or scenario.metadata.get("semantic_family")
        or ""
    )
    unsupported = (
        semantic_family == UNSUPPORTED_SEMANTIC_FAMILY
        or raw.get("semantic_plan_status") == "unsupported"
        or raw.get("unsupported_boundary_returned") is True
        or raw.get("unsupported_capability") is True
    )
    supported = bool(semantic_family) and not unsupported
    return {
        "support_status": "unsupported" if unsupported else "supported" if supported else "",
        "plan_family": semantic_family,
        "preview_hash": str(raw.get("preview_hash") or raw.get("semantic_preview_hash") or ""),
        "builder_refs": _string_tuple(raw.get("source_builder_refs") or raw.get("builder_refs") or raw.get("plan_builder_refs") or ()),
        "unsupported_boundary_reason": str(raw.get("unsupported_boundary_reason") or raw.get("blocked_reason") or ""),
        "verification_status": str(raw.get("verification_status") or ""),
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return (str(value),) if str(value) else ()


def _write_summary(path: Path, *, args: argparse.Namespace, records: Sequence[BatchRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario_set": args.scenario_set,
        "wwise_version": args.wwise_version,
        "require_live": args.require_live,
        "prefer_live": args.prefer_live,
        "workspace": args.workspace,
        "archive_root": args.archive_root,
        "records": [asdict(record) for record in records],
        "counts": {verdict: sum(1 for record in records if record.verdict == verdict) for verdict in ("pass", "fail", "skip", "blocked")},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario-set",
        choices=(
            "phase3-required",
            "phase3-smoke",
            SEMANTIC_CAPABILITY_REQUIRED_SET,
            SEMANTIC_CAPABILITY_ALL_SET,
            SEMANTIC_CAPABILITY_BOUNDARY_SET,
        ),
        required=True,
    )
    parser.add_argument("--wwise-version", choices=(*SUPPORTED_WWISE_VERSIONS, "all"), required=True)
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--prefer-live", action="store_true")
    args = parser.parse_args(argv)
    if args.require_live and args.prefer_live:
        parser.error("--require-live and --prefer-live are mutually exclusive")
    return args


if __name__ == "__main__":
    raise SystemExit(main())

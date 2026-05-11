from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.semantic.run_opencode_semantic_batch import (  # pyright: ignore[reportMissingImports]
    SUMMARY_2022_FILENAME,
    SUMMARY_2022_PATH,
    SUMMARY_MULTIVERSION_FILENAME,
    SUMMARY_MULTIVERSION_PATH,
    VersionPrerequisites,
    check_version_prerequisites,
    run_batch,
    _scenario_prompt,
)
from tests.semantic.scenarios import (  # pyright: ignore[reportMissingImports]
    PUBLIC_CONFIG_FIELDS,
    SEMANTIC_CAPABILITY_REQUIRED_FAMILIES,
    SEMANTIC_CAPABILITY_SCENARIO_SET,
    SUPPORTED_WWISE_VERSIONS,
    evaluate_scenario_output,
    phase3_scenarios,
    scenarios_for_set,
)
from tests.semantic.support.opencode_harness import (  # pyright: ignore[reportMissingImports]
    OpenCodeHarnessConfig,
    OpenCodeSemanticHarness,
    SkillSymlinkRequirement,
    WwiseSandboxMetadata,
)


def test_phase3_required_scenarios_load_all_must_cover_cases() -> None:
    scenarios = scenarios_for_set("phase3-required")
    ids = {scenario.id for scenario in scenarios}

    assert ids == {
        "phase3-readonly-bus-listing",
        "phase3-waql-master-mixer-ui-descendants",
        "phase3-public-config-boundary",
        "phase3-invalid-parent-mutation-preview",
        "phase3-confirm-live-mutation-verify",
        "phase3-compound-read-then-confirm",
    }
    smoke_ids = {scenario.id for scenario in scenarios_for_set("phase3-smoke")}
    assert smoke_ids == {"phase3-readonly-bus-listing", "phase3-waql-master-mixer-ui-descendants"}


def test_semantic_capability_scenarios_cover_required_families() -> None:
    scenarios = scenarios_for_set(SEMANTIC_CAPABILITY_SCENARIO_SET)

    assert tuple(scenario.id for scenario in scenarios) == SEMANTIC_CAPABILITY_REQUIRED_FAMILIES
    assert tuple(scenario.family for scenario in scenarios) == SEMANTIC_CAPABILITY_REQUIRED_FAMILIES
    assert all("phase3-required" not in scenario.scenario_sets for scenario in scenarios)
    assert all("phase3-smoke" not in scenario.scenario_sets for scenario in scenarios)


def test_semantic_capability_evaluator_requires_planner_facts() -> None:
    supported = _scenario("semantic-capability-crud-preview")
    unsupported = _scenario("semantic-capability-runtime-unsupported")

    prose_only = evaluate_scenario_output(
        supported,
        "I can prepare a safe preview plan with no mutation, using the right Wwise builders.",
    )
    missing_builder = evaluate_scenario_output(
        supported,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "structured_intent_extracted": True,
                "semantic_family": "crud_authoring",
                "semantic_planner_invoked": True,
                "semantic_plan_status": "preview_ready",
                "preview_hash": "sha256:preview",
                "mutation_executed": False,
            }
        ),
    )
    supported_pass = evaluate_scenario_output(supported, _capability_facts(supported))
    unsupported_missing_boundary = evaluate_scenario_output(
        unsupported,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "structured_intent_extracted": True,
                "semantic_family": "unsupported_runtime_boundary",
                "semantic_planner_invoked": True,
                "mutation_executed": False,
            }
        ),
    )
    unsupported_execution_claim = evaluate_scenario_output(
        unsupported,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "structured_intent_extracted": True,
                "semantic_family": "unsupported_runtime_boundary",
                "semantic_planner_invoked": True,
                "unsupported_boundary_returned": True,
                "scheduler_executed": True,
                "mutation_executed": False,
            }
        ),
    )
    unsupported_pass = evaluate_scenario_output(unsupported, _capability_facts(unsupported))

    assert prose_only.verdict == "fail"
    assert any("structured intent" in note for note in prose_only.failure_notes)
    assert any("semantic planner" in note for note in prose_only.failure_notes)
    assert missing_builder.verdict == "fail"
    assert any("builder provenance" in note for note in missing_builder.failure_notes)
    assert supported_pass.verdict == "pass"
    assert unsupported_missing_boundary.verdict == "fail"
    assert any("unsupported capability boundary" in note for note in unsupported_missing_boundary.failure_notes)
    assert unsupported_execution_claim.verdict == "fail"
    assert any("unsupported runtime/cross-app execution" in note for note in unsupported_execution_claim.failure_notes)
    assert unsupported_pass.verdict == "pass"


def test_read_only_and_waql_verdicts_fail_on_repo_doc_first_drift() -> None:
    readonly = _scenario("phase3-readonly-bus-listing")
    waql = _scenario("phase3-waql-master-mixer-ui-descendants")
    drift_output = "I will inspect the repository docs first. Later I may call ak.wwise.core.object.get through WAAPI."

    readonly_verdict = evaluate_scenario_output(readonly, drift_output)
    waql_verdict = evaluate_scenario_output(
        waql,
        'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, "waapi_calls": ["ak.wwise.core.object.get"], '
        '"research_before_live_waapi": true, "descendant_query_root": "Master-Mixer Hierarchy"}',
    )

    assert readonly_verdict.verdict == "fail"
    assert any("repo/docs/source research" in note for note in readonly_verdict.failure_notes)
    assert waql_verdict.verdict == "fail"
    assert any("repo/docs/source research" in note for note in waql_verdict.failure_notes)


def test_read_only_and_waql_pass_with_live_waapi_before_research_facts() -> None:
    readonly = _scenario("phase3-readonly-bus-listing")
    waql = _scenario("phase3-waql-master-mixer-ui-descendants")

    readonly_verdict = evaluate_scenario_output(
        readonly,
        'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, "live_waapi_before_research": true, '
        '"waapi_calls": ["ak.wwise.core.object.get"], "mutation_executed": false}',
    )
    waql_verdict = evaluate_scenario_output(
        waql,
        'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, "live_waapi_before_research": true, '
        '"waapi_calls": ["ak.wwise.core.object.get"], "mutation_executed": false, '
        '"descendant_query_root": "Master-Mixer Hierarchy"}',
    )

    assert readonly_verdict.verdict == "pass"
    assert waql_verdict.verdict == "pass"


def test_semantic_fact_extraction_skips_invalid_instruction_marker_and_uses_later_json() -> None:
    readonly = _scenario("phase3-readonly-bus-listing")
    output = (
        "Prompt echoed this instruction: SEMANTIC_RESULT_JSON: containing behavioral facts, not JSON.\n"
        "Some assistant prose before the final machine-readable line.\n"
        'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": false, "waapi_calls": []}\n'
        'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, "live_waapi_before_research": true, '
        '"waapi_calls": ["ak.wwise.core.object.get"], "mutation_executed": false}\n'
    )

    verdict = evaluate_scenario_output(readonly, output)

    assert verdict.verdict == "pass"
    assert verdict.facts["live_waapi_attempted"] is True
    assert verdict.facts["waapi_calls"] == ["ak.wwise.core.object.get"]


def test_semantic_fact_extraction_reads_opencode_json_event_part_text() -> None:
    scenario = _scenario("phase3-invalid-parent-mutation-preview")
    event = {
        "type": "text",
        "part": {
            "type": "text",
            "text": (
                'SEMANTIC_RESULT_JSON: {"preview_ready": true, "confirmation_required": true, '
                '"mutation_executed": false, "invalid_parent_rewritten_silently": false, '
                '"candidate_target_explained": true}'
            ),
        },
    }

    verdict = evaluate_scenario_output(scenario, json.dumps(event))

    assert verdict.verdict == "pass"
    assert verdict.facts["preview_ready"] is True
    assert verdict.facts["candidate_target_explained"] is True


def test_semantic_fact_extraction_ignores_raw_prompt_marker_before_decoded_event_text() -> None:
    scenario = _scenario("phase3-readonly-bus-listing")
    raw_prompt_echo = "Prompt said SEMANTIC_RESULT_JSON: followed by a valid one-line JSON object, not actual JSON."
    event = {
        "type": "text",
        "part": {
            "type": "text",
            "text": (
                'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, '
                '"live_waapi_before_research": true, '
                '"waapi_calls": ["ak.wwise.core.object.get"], "mutation_executed": false}'
            ),
        },
    }
    output = raw_prompt_echo + "\n" + json.dumps(event)

    verdict = evaluate_scenario_output(scenario, output)

    assert verdict.verdict == "pass"
    assert verdict.facts["live_waapi_attempted"] is True
    assert verdict.facts["waapi_calls"] == ["ak.wwise.core.object.get"]


def test_public_config_boundary_rejects_internal_runtime_fields() -> None:
    scenario = _scenario("phase3-public-config-boundary")
    output = (
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "public_config_fields": sorted(PUBLIC_CONFIG_FIELDS | {"WWISE_CONSOLE"}),
                "internal_config_fields": ["WWISE_CONSOLE"],
            }
        )
    )

    verdict = evaluate_scenario_output(scenario, output)

    assert verdict.verdict == "fail"
    assert any("internal runtime fields" in note for note in verdict.failure_notes)


def test_mutation_preview_assertions_enforce_confirmation_safety() -> None:
    scenario = _scenario("phase3-invalid-parent-mutation-preview")

    verdict = evaluate_scenario_output(
        scenario,
        'SEMANTIC_RESULT_JSON: {"preview_ready": true, "confirmation_required": true, '
        '"mutation_executed": true, "invalid_parent_rewritten_silently": false, "candidate_target_explained": true}',
    )

    assert verdict.verdict == "fail"
    assert any("Mutation executed" in note or "mutation executed" in note for note in verdict.failure_notes)


def test_confirmed_mutation_fails_on_preview_execution_identity_mismatch() -> None:
    scenario = _scenario("phase3-confirm-live-mutation-verify")

    verdict = evaluate_scenario_output(
        scenario,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "confirmation_observed": True,
                "mutation_executed_before_confirmation": False,
                "mutation_executed": True,
                "preview_target_identity": {"path": "\\Master-Mixer Hierarchy"},
                "execution_target_identity": {"path": "\\Master-Mixer Hierarchy\\Default Work Unit"},
                "verification_status": "verified",
            }
        ),
    )

    assert verdict.verdict == "fail"
    assert any("identity differs" in note for note in verdict.failure_notes)


def test_confirmed_mutation_passes_when_role_target_identity_matches_with_preview_policy_metadata() -> None:
    scenario = _scenario("phase3-confirm-live-mutation-verify")
    parent_identity = {
        "resolved": {
            "identity": {"path": "\\Master-Mixer Hierarchy\\Default Work Unit"},
            "object": "{A74EEB4A-0805-4AFA-969C-53DCB862B550}",
            "row": {"id": "{A74EEB4A-0805-4AFA-969C-53DCB862B550}", "name": "Default Work Unit"},
        },
        "object": "{A74EEB4A-0805-4AFA-969C-53DCB862B550}",
        "target_key": ["\\Master-Mixer Hierarchy\\Default Work Unit"],
    }
    preview_identity = {
        "roles": {"parent": parent_identity},
        "confirmed_execution": {
            "required": True,
            "abort_on_mismatch": True,
            "mismatch_status": "repreview_required",
        },
    }
    execution_identity = {"roles": {"parent": parent_identity}}

    verdict = evaluate_scenario_output(
        scenario,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "confirmation_observed": True,
                "mutation_executed_before_confirmation": False,
                "mutation_executed": True,
                "preview_target_identity": preview_identity,
                "execution_target_identity": execution_identity,
                "verification_status": "verified",
            }
        ),
    )

    assert verdict.verdict == "pass"


def test_confirmed_mutation_still_fails_when_role_target_key_differs_despite_same_shape() -> None:
    scenario = _scenario("phase3-confirm-live-mutation-verify")

    verdict = evaluate_scenario_output(
        scenario,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "confirmation_observed": True,
                "mutation_executed_before_confirmation": False,
                "mutation_executed": True,
                "preview_target_identity": {
                    "roles": {"parent": {"target_key": ["\\Master-Mixer Hierarchy\\Default Work Unit"]}},
                    "confirmed_execution": {"required": True},
                },
                "execution_target_identity": {
                    "roles": {"parent": {"target_key": ["\\Actor-Mixer Hierarchy\\Default Work Unit"]}}
                },
                "verification_status": "verified",
            }
        ),
    )

    assert verdict.verdict == "fail"
    assert any("identity differs" in note for note in verdict.failure_notes)


def test_confirmed_mutation_passes_with_direct_parent_role_map_from_live_output() -> None:
    scenario = _scenario("phase3-confirm-live-mutation-verify")
    parent_identity = {
        "object": "\\\\Master-Mixer Hierarchy\\\\Default Work Unit",
        "resolved": {
            "identity": {
                "id": None,
                "name": None,
                "parent": None,
                "path": "\\\\Master-Mixer Hierarchy\\\\Default Work Unit",
                "type": None,
                "waql": None,
            },
            "object": "\\\\Master-Mixer Hierarchy\\\\Default Work Unit",
            "resolution": "exact-path",
            "row": {"id": "{A74EEB4A-0805-4AFA-969C-53DCB862B550}", "name": "Default Work Unit"},
        },
        "target_key": ["\\\\Master-Mixer Hierarchy\\\\Default Work Unit"],
    }

    verdict = evaluate_scenario_output(
        scenario,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "confirmation_observed": True,
                "mutation_executed_before_confirmation": False,
                "mutation_executed": True,
                "preview_target_identity": {"parent": parent_identity},
                "execution_target_identity": {"parent": parent_identity},
                "verification_status": "verified",
            }
        ),
    )

    assert verdict.verdict == "pass"


def test_confirmed_mutation_fails_with_direct_parent_role_map_target_mismatch() -> None:
    scenario = _scenario("phase3-confirm-live-mutation-verify")

    verdict = evaluate_scenario_output(
        scenario,
        "SEMANTIC_RESULT_JSON: "
        + json.dumps(
            {
                "confirmation_observed": True,
                "mutation_executed_before_confirmation": False,
                "mutation_executed": True,
                "preview_target_identity": {
                    "parent": {"target_key": ["\\\\Master-Mixer Hierarchy\\\\Default Work Unit"]},
                    "confirmed_execution": {"required": True},
                },
                "execution_target_identity": {
                    "parent": {"target_key": ["\\\\Master-Mixer Hierarchy\\\\Other Work Unit"]}
                },
                "verification_status": "verified",
            }
        ),
    )

    assert verdict.verdict == "fail"
    assert any("identity differs" in note for note in verdict.failure_notes)


def test_compound_read_then_confirm_requires_read_before_mutation() -> None:
    scenario = _scenario("phase3-compound-read-then-confirm")

    verdict = evaluate_scenario_output(
        scenario,
        'SEMANTIC_RESULT_JSON: {"read_stage_completed": true, "read_stage_completed_before_mutation": false, '
        '"live_waapi_before_research": true, "mutation_executed_before_confirmation": false, "confirmation_required": true}',
    )

    assert verdict.verdict == "fail"
    assert any("before read completion" in note for note in verdict.failure_notes)


def test_mocked_nonlive_batch_writes_archives_and_summary(tmp_path: Path) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-required",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(archive_root),
        ]
    )

    assert exit_code == 0
    records = sorted(archive_root.glob("*/phase3-*/record.json"))
    assert len(records) == 6
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in records]
    assert {payload["verdict"] for payload in payloads} == {"pass"}
    assert all(payload["archive_policy"]["references_only"] is True for payload in payloads)
    for payload in payloads:
        assert payload["command_line"][:4] == ["opencode", "run", "--attach", "http://127.0.0.1:4096"]
        assert payload["command_line"][4:8] == ["--dir", str(workspace.resolve(strict=False)), "--format", "json"]


def test_live_prerequisite_check_accepts_custom_workspace_symlink(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    console = tmp_path / "WwiseConsole.sh"
    sample_project = tmp_path / "SampleProject.wproj"
    console.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    console.chmod(0o755)
    sample_project.write_text("<WwiseDocument/>\n", encoding="utf-8")
    monkeypatch.setattr(
        "tests.semantic.run_opencode_semantic_batch._version_paths",
        lambda version: {"console": str(console), "sample_project": str(sample_project)},
    )

    prerequisites = check_version_prerequisites("2022.1", workspace)

    assert prerequisites.available is True
    assert prerequisites.missing == ()


def test_live_prerequisite_check_reports_missing_custom_workspace_symlink(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "custom-workspace"
    console = tmp_path / "WwiseConsole.sh"
    sample_project = tmp_path / "SampleProject.wproj"
    console.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    console.chmod(0o755)
    sample_project.write_text("<WwiseDocument/>\n", encoding="utf-8")
    monkeypatch.setattr(
        "tests.semantic.run_opencode_semantic_batch._version_paths",
        lambda version: {"console": str(console), "sample_project": str(sample_project)},
    )

    prerequisites = check_version_prerequisites("2022.1", workspace)

    assert prerequisites.available is False
    assert any(str(workspace / ".agents" / "skills" / "waapi-skill") in item for item in prerequisites.missing)
    assert any("missing OpenCode skill workspace symlink" in item for item in prerequisites.missing)


def test_live_batch_prompts_include_dynamic_sandbox_waapi_metadata(tmp_path: Path) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"
    sandbox_metadata = tmp_path / "sandbox-metadata.json"
    sandbox_metadata.write_text("{}\n", encoding="utf-8")

    def available(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path="/mock/WwiseConsole.sh",
            sample_project_path="/mock/SampleProject.wproj",
            available=True,
            missing=(),
        )

    def harness_factory(version: str, checked_workspace: Path, live: bool) -> OpenCodeSemanticHarness:
        assert live is True
        install = checked_workspace / ".agents" / "skills" / "waapi-skill"
        source = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            prompt = command[-1]
            assert "wwise_version=2022.1" in prompt
            assert "waapi_host=127.0.0.1" in prompt
            assert "waapi_port=64502" in prompt
            assert "stale saved config" in prompt
            assert "Do not spawn research, explore, librarian, or documentation subagents" in prompt
            assert "immediately provide the final answer and SEMANTIC_RESULT_JSON" in prompt
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "Session: ses_dynamic_port\n"
                    'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, '
                    '"live_waapi_before_research": true, '
                    '"waapi_calls": ["ak.wwise.core.object.get"], '
                    '"descendant_query_root": "Master-Mixer Hierarchy", '
                    '"mutation_executed": false}\n'
                ),
                stderr="",
            )

        return OpenCodeSemanticHarness(
            OpenCodeHarnessConfig(
                workspace=checked_workspace,
                skill_requirement=SkillSymlinkRequirement(install_path=install, source_path=source),
                wwise=WwiseSandboxMetadata(
                    wwise_version=version,
                    waapi_host="127.0.0.1",
                    waapi_port=64502,
                    sandbox_metadata_path=sandbox_metadata,
                ),
                live=False,
            ),
            runner=runner,
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-smoke",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(archive_root),
            "--prefer-live",
        ],
        prerequisite_checker=available,
        harness_factory=harness_factory,
    )

    assert exit_code == 0
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(archive_root.glob("*/phase3-*/record.json"))]
    assert len(payloads) == 2
    for payload in payloads:
        prompt = payload["command_line"][-1]
        assert "waapi_port=64502" in prompt
        assert payload["prompt"] == prompt


def test_live_public_config_prompt_does_not_incentivize_internal_field_listing() -> None:
    prompt = _scenario_prompt(
        _scenario("phase3-public-config-boundary"),
        live_metadata=WwiseSandboxMetadata(wwise_version="2022.1", waapi_host="127.0.0.1", waapi_port=64502),
    )

    assert "saved public config fields: wwise_version, waapi_host, waapi_port, project_modification_policy" in prompt
    assert "Do not enumerate WwiseConsole paths" in prompt
    assert "set public_config_fields to exactly those four public fields" in prompt
    assert "set internal_config_fields to []" in prompt


def test_live_confirmed_mutation_prompt_uses_repeatable_generated_name() -> None:
    prompt = _scenario_prompt(
        _scenario("phase3-confirm-live-mutation-verify"),
        live_metadata=WwiseSandboxMetadata(wwise_version="2022.1", waapi_host="127.0.0.1", waapi_port=64502),
        semantic_object_name="Temp_UI_Bus_abcd1234",
    )

    assert "called Temp_UI_Bus_abcd1234" in prompt
    assert "called Temp_UI_Bus." not in prompt
    assert "Use the exact object name `Temp_UI_Bus_abcd1234`" in prompt
    assert "Treat `SEMANTIC FOLLOW-UP: confirm` as the explicit user confirmation" in prompt


def test_live_invalid_preview_prompt_forbids_research_and_requires_immediate_preview_json() -> None:
    prompt = _scenario_prompt(
        _scenario("phase3-invalid-parent-mutation-preview"),
        live_metadata=WwiseSandboxMetadata(wwise_version="2022.1", waapi_host="127.0.0.1", waapi_port=64502),
        semantic_object_name="Temp_UI_Bus_preview42",
    )

    assert "INVALID-PARENT PREVIEW CONSTRAINTS" in prompt
    assert "Do not spawn research, explore, librarian, documentation, planning, or background subagents" in prompt
    assert "Resolve/check `Master-Mixer Hierarchy`" in prompt
    assert "candidate writable `Default Work Unit`" in prompt
    assert "Produce a preview only; do not create or mutate anything" in prompt
    assert "Immediately emit final SEMANTIC_RESULT_JSON" in prompt
    assert "Do not wait for background tasks" in prompt


def test_live_compound_prompt_forbids_research_and_requires_immediate_read_preview_json() -> None:
    prompt = _scenario_prompt(
        _scenario("phase3-compound-read-then-confirm"),
        live_metadata=WwiseSandboxMetadata(wwise_version="2022.1", waapi_host="127.0.0.1", waapi_port=64502),
        semantic_object_name="Temp_UI_Bus_compound42",
    )

    assert "COMPOUND READ-THEN-CONFIRM CONSTRAINTS" in prompt
    assert "Do not spawn research, explore, librarian, documentation, planning, or background subagents" in prompt
    assert "Complete the read stage first using live ak.wwise.core.object.get" in prompt
    assert "prepare the preview target under `Master-Mixer Hierarchy`" in prompt
    assert "Stop for confirmation; do not execute the create" in prompt
    assert "Immediately emit final SEMANTIC_RESULT_JSON" in prompt
    assert "Do not wait for background tasks" in prompt


def test_live_batch_uses_distinct_generated_semantic_names_for_mutation_prompts(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"
    captured_prompts: list[str] = []

    def generated_names(scenarios):
        return {scenario.id: f"Temp_UI_Bus_{scenario.id.replace('-', '_')}_fixed42" for scenario in scenarios if "Temp_UI_Bus" in scenario.prompt}

    monkeypatch.setattr("tests.semantic.run_opencode_semantic_batch._semantic_object_names", generated_names)

    def available(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path="/mock/WwiseConsole.sh",
            sample_project_path="/mock/SampleProject.wproj",
            available=True,
            missing=(),
        )

    def harness_factory(version: str, checked_workspace: Path, live: bool) -> OpenCodeSemanticHarness:
        assert live is True
        install = checked_workspace / ".agents" / "skills" / "waapi-skill"
        source = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            prompt = command[-1]
            captured_prompts.append(prompt)
            return subprocess.CompletedProcess(command, 0, stdout=_passing_semantic_output(prompt), stderr="")

        return OpenCodeSemanticHarness(
            OpenCodeHarnessConfig(
                workspace=checked_workspace,
                skill_requirement=SkillSymlinkRequirement(install_path=install, source_path=source),
                wwise=WwiseSandboxMetadata(wwise_version=version, waapi_port=64502, sandbox_metadata_path=tmp_path / "sandbox.json"),
                live=False,
            ),
            runner=runner,
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-required",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(archive_root),
            "--require-live",
        ],
        prerequisite_checker=available,
        harness_factory=harness_factory,
    )

    assert exit_code == 0
    mutation_prompts = [prompt for prompt in captured_prompts if "Create a new bus" in prompt or "prepare to create" in prompt]
    assert len(mutation_prompts) == 3
    assert "Temp_UI_Bus_phase3_invalid_parent_mutation_preview_fixed42" in mutation_prompts[0]
    assert "Temp_UI_Bus_phase3_confirm_live_mutation_verify_fixed42" in mutation_prompts[1]
    assert "Temp_UI_Bus_phase3_compound_read_then_confirm_fixed42" in mutation_prompts[2]
    assert len({prompt.split("Temp_UI_Bus_phase3_", 1)[1].split(" ", 1)[0] for prompt in mutation_prompts}) == 3
    assert all("Temp_UI_Bus under" not in prompt for prompt in mutation_prompts)


def test_prefer_live_all_versions_records_explicit_skips_for_unavailable_versions(tmp_path: Path) -> None:
    custom_workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"

    def unavailable(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == custom_workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path=f"/missing/{version}/WwiseConsole.sh",
            sample_project_path=f"/missing/{version}/SampleProject.wproj",
            available=False,
            missing=(f"missing executable WwiseConsole for {version}",),
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-smoke",
            "--wwise-version",
            "all",
            "--workspace",
            str(custom_workspace),
            "--archive-root",
            str(archive_root),
            "--prefer-live",
        ],
        prerequisite_checker=unavailable,
    )

    assert exit_code == 0
    records = sorted(archive_root.glob("*/phase3-*/record.json"))
    assert len(records) == len(SUPPORTED_WWISE_VERSIONS) * 2
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in records]
    assert {payload["verdict"] for payload in payloads} == {"skip"}
    assert {payload["wwise_version"] for payload in payloads} == set(SUPPORTED_WWISE_VERSIONS)
    assert all(payload["failure_notes"] for payload in payloads)


def test_temp_archive_runs_do_not_overwrite_repo_task_10_summaries(tmp_path: Path) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    required_archive_root = tmp_path / "required-archive"
    smoke_archive_root = tmp_path / "smoke-archive"
    before_required = SUMMARY_2022_PATH.read_bytes() if SUMMARY_2022_PATH.exists() else None
    before_smoke = SUMMARY_MULTIVERSION_PATH.read_bytes() if SUMMARY_MULTIVERSION_PATH.exists() else None

    def unavailable(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path=f"/missing/{version}/WwiseConsole.sh",
            sample_project_path=f"/missing/{version}/SampleProject.wproj",
            available=False,
            missing=(f"missing executable WwiseConsole for {version}",),
        )

    required_exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-required",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(required_archive_root),
            "--require-live",
        ],
        prerequisite_checker=unavailable,
    )
    smoke_exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-smoke",
            "--wwise-version",
            "all",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(smoke_archive_root),
            "--prefer-live",
        ],
        prerequisite_checker=unavailable,
    )

    assert required_exit_code == 1
    assert smoke_exit_code == 0
    assert required_archive_root.joinpath(SUMMARY_2022_FILENAME).is_file()
    assert smoke_archive_root.joinpath(SUMMARY_MULTIVERSION_FILENAME).is_file()
    assert _read_optional_bytes(SUMMARY_2022_PATH) == before_required
    assert _read_optional_bytes(SUMMARY_MULTIVERSION_PATH) == before_smoke


def test_prefer_live_returns_nonzero_for_semantic_fail_verdicts(tmp_path: Path) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"

    def available(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path="/mock/WwiseConsole.sh",
            sample_project_path="/mock/SampleProject.wproj",
            available=True,
            missing=(),
        )

    def harness_factory(version: str, checked_workspace: Path, live: bool) -> OpenCodeSemanticHarness:
        assert live is True
        install = checked_workspace / ".agents" / "skills" / "waapi-skill"
        source = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "Session: ses_semantic_fail\n"
                    'SEMANTIC_RESULT_JSON: {"live_waapi_attempted": true, '
                    '"waapi_calls": ["ak.wwise.core.object.get"], '
                    '"research_before_live_waapi": true, '
                    '"descendant_query_root": "Master-Mixer Hierarchy", '
                    '"mutation_executed": false}\n'
                ),
                stderr="",
            )

        return OpenCodeSemanticHarness(
            OpenCodeHarnessConfig(
                workspace=checked_workspace,
                skill_requirement=SkillSymlinkRequirement(install_path=install, source_path=source),
                wwise=WwiseSandboxMetadata(wwise_version=version, sandbox_metadata_path=tmp_path / "sandbox-metadata.json"),
                live=False,
            ),
            runner=runner,
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-smoke",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(archive_root),
            "--prefer-live",
        ],
        prerequisite_checker=available,
        harness_factory=harness_factory,
    )

    assert exit_code == 1
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(archive_root.glob("*/phase3-*/record.json"))]
    assert len(payloads) == 2
    assert {payload["verdict"] for payload in payloads} == {"fail"}


def test_prefer_live_returns_nonzero_for_available_version_blocked_live_attempt(tmp_path: Path) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"

    def available(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path="/mock/WwiseConsole.sh",
            sample_project_path="/mock/SampleProject.wproj",
            available=True,
            missing=(),
        )

    def harness_factory(version: str, checked_workspace: Path, live: bool) -> OpenCodeSemanticHarness:
        assert live is True
        install = checked_workspace / ".agents" / "skills" / "waapi-skill"
        source = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 4, stdout="No OpenCode session header\n", stderr="attach failed\n")

        return OpenCodeSemanticHarness(
            OpenCodeHarnessConfig(
                workspace=checked_workspace,
                skill_requirement=SkillSymlinkRequirement(install_path=install, source_path=source),
                wwise=WwiseSandboxMetadata(wwise_version=version, sandbox_metadata_path=tmp_path / "sandbox-metadata.json"),
                live=False,
            ),
            runner=runner,
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-smoke",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(archive_root),
            "--prefer-live",
        ],
        prerequisite_checker=available,
        harness_factory=harness_factory,
    )

    assert exit_code == 1
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(archive_root.glob("*/phase3-*/record.json"))]
    assert len(payloads) == 2
    assert {payload["verdict"] for payload in payloads} == {"blocked"}
    for payload in payloads:
        assert payload["command_line"][:4] == ["opencode", "run", "--attach", "http://127.0.0.1:4096"]
        assert payload["command_line"][4:8] == ["--dir", str(workspace.resolve(strict=False)), "--format", "json"]


def test_require_live_unavailable_version_returns_blocked_evidence(tmp_path: Path) -> None:
    custom_workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"

    def unavailable(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == custom_workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path="/missing/WwiseConsole.sh",
            sample_project_path="/missing/SampleProject.wproj",
            available=False,
            missing=("missing executable WwiseConsole", "missing SampleProject .wproj"),
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-required",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(custom_workspace),
            "--archive-root",
            str(archive_root),
            "--require-live",
        ],
        prerequisite_checker=unavailable,
    )

    assert exit_code == 1
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(archive_root.glob("*/phase3-*/record.json"))]
    assert len(payloads) == 6
    assert {payload["verdict"] for payload in payloads} == {"blocked"}
    assert all("missing executable WwiseConsole" in " ".join(payload["failure_notes"]) for payload in payloads)


def test_post_command_missing_session_blocked_archive_keeps_command_output_and_status(tmp_path: Path) -> None:
    workspace = _workspace_with_symlink(tmp_path)
    archive_root = tmp_path / "archive"

    def available(version: str, checked_workspace: Path) -> VersionPrerequisites:
        assert checked_workspace == workspace.resolve(strict=False)
        return VersionPrerequisites(
            version=version,
            console_path="/mock/WwiseConsole.sh",
            sample_project_path="/mock/SampleProject.wproj",
            available=True,
            missing=(),
        )

    def harness_factory(version: str, checked_workspace: Path, live: bool) -> OpenCodeSemanticHarness:
        assert live is True
        install = checked_workspace / ".agents" / "skills" / "waapi-skill"
        source = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                9,
                stdout="ConnectionRefusedError(61, connect failed)\nOpenCode produced no session header\n",
                stderr="attach stderr details\n",
            )

        return OpenCodeSemanticHarness(
            OpenCodeHarnessConfig(
                workspace=checked_workspace,
                skill_requirement=SkillSymlinkRequirement(install_path=install, source_path=source),
                wwise=WwiseSandboxMetadata(wwise_version=version, sandbox_metadata_path=tmp_path / "sandbox-metadata.json"),
                live=False,
            ),
            runner=runner,
        )

    exit_code = run_batch(
        [
            "--scenario-set",
            "phase3-required",
            "--wwise-version",
            "2022.1",
            "--workspace",
            str(workspace),
            "--archive-root",
            str(archive_root),
            "--require-live",
        ],
        prerequisite_checker=available,
        harness_factory=harness_factory,
    )

    assert exit_code == 1
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(archive_root.glob("*/phase3-*/record.json"))]
    assert len(payloads) == 6
    assert {payload["verdict"] for payload in payloads} == {"blocked"}
    for payload in payloads:
        assert payload["command_line"][:4] == ["opencode", "run", "--attach", "http://127.0.0.1:4096"]
        assert payload["command_line"][4:8] == ["--dir", str(workspace.resolve(strict=False)), "--format", "json"]
        assert "ConnectionRefusedError" in payload["assistant_output"]
        assert "attach stderr details" in payload["assistant_output"]
        assert payload["command_exit_status"] == 9
        assert any("output_summary=" in note and "ConnectionRefusedError" in note for note in payload["failure_notes"])


def _passing_semantic_output(prompt: str) -> str:
    lowered = prompt.lower()
    if "what do i need to configure" in lowered:
        facts = {
            "public_config_fields": sorted(PUBLIC_CONFIG_FIELDS),
            "internal_config_fields": [],
        }
    elif "semantic follow-up" in lowered and "confirm" in lowered:
        identity = {"path": "\\Master-Mixer Hierarchy\\Default Work Unit", "type": "WorkUnit"}
        facts = {
            "confirmation_observed": True,
            "mutation_executed_before_confirmation": False,
            "mutation_executed": True,
            "preview_target_identity": identity,
            "execution_target_identity": identity,
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
    elif "descendant under master-mixer hierarchy" in lowered:
        facts = {
            "live_waapi_attempted": True,
            "live_waapi_before_research": True,
            "waapi_calls": ["ak.wwise.core.object.get"],
            "descendant_query_root": "Master-Mixer Hierarchy",
            "mutation_executed": False,
        }
    else:
        facts = {
            "live_waapi_attempted": True,
            "live_waapi_before_research": True,
            "waapi_calls": ["ak.wwise.core.object.get"],
            "mutation_executed": False,
        }
    return "Session: ses_test\nSEMANTIC_RESULT_JSON: " + json.dumps(facts, sort_keys=True) + "\n"


def _capability_facts(scenario) -> str:
    facts = {
        "structured_intent_extracted": True,
        "semantic_family": scenario.metadata["semantic_family"],
        "semantic_planner_invoked": True,
        "live_waapi_ready": True,
        "live_waapi_before_research": True,
        "mutation_executed_before_confirmation": False,
        "mutation_executed": False,
    }
    if scenario.id.endswith("unsupported"):
        facts.update(
            {
                "semantic_plan_status": "unsupported",
                "unsupported_boundary_returned": True,
            }
        )
    else:
        facts.update(
            {
                "semantic_plan_status": "preview_ready",
                "builder_backed_plan_produced": True,
                "source_builder_refs": ["wwise_waapi.builders.common"],
            }
        )
        if scenario.metadata.get("requires_preview_hash"):
            facts["preview_hash"] = "sha256:semantic-preview"
        if scenario.metadata.get("allows_confirmed_mutation"):
            facts.update(
                {
                    "confirmation_observed": True,
                    "mutation_executed": True,
                    "verification_status": "verified",
                }
            )
    return "SEMANTIC_RESULT_JSON: " + json.dumps(facts, sort_keys=True)


def _scenario(scenario_id: str):
    for scenario in phase3_scenarios():
        if scenario.id == scenario_id:
            return scenario
    raise AssertionError(f"missing scenario: {scenario_id}")


def _workspace_with_symlink(tmp_path: Path) -> Path:
    install = tmp_path / "workspace" / ".agents" / "skills" / "waapi-skill"
    install.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
    install.symlink_to(source, target_is_directory=True)
    return tmp_path / "workspace"


def _read_optional_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None

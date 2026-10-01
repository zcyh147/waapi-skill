from __future__ import annotations

from dataclasses import replace
import json
import hashlib
from pathlib import Path

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix


PROFILE = "integration_expansion_v1"


def _options(tmp_path, monkeypatch, surface="matrix", *extra):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("codex", "auth.json", "live.json"):
        (tmp_path / name).write_text("{}")
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda value: Path(value).resolve())
    args = ["--profile", PROFILE, "--codex-binary", str(tmp_path / "codex"),
            "--auth-json", str(tmp_path / "auth.json"), "--live-config", str(tmp_path / "live.json")]
    args += (["--campaign-root", str(tmp_path / "campaign")] if surface == "campaign"
             else ["--iteration-root", str(tmp_path / "matrix")])
    return (campaign.parse_args if surface == "campaign" else matrix.parse_args)([*args, *extra])


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_expansion_defaults_and_complete_selection(tmp_path, monkeypatch, surface):
    options = _options(tmp_path, monkeypatch, surface)
    assert (options.model, options.reasoning_effort, options.service_tier) == ("gpt-6-luna", "high", "default")
    assert options.timeout_seconds == 600
    units = (campaign.load_heavy_v3_campaign_units if surface == "campaign" else matrix.load_heavy_v3_units)(options)
    assert len(units) == 14
    assert sum(unit.evidence_kind == "agent_acceptance" for unit in units) == 13
    boundary, = (unit for unit in units if unit.evidence_kind == "capability_boundary")
    assert boundary.unit_id == "EXP22-M05"
    assert (boundary.user_turn_count, boundary.transaction_count) == (0, 0)


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
@pytest.mark.parametrize("selection,expected", (
    (("--case-id", "C01", "--case-id", "M01", "--case-id", "C06", "--version", "2025.1"),
     ("EXP25-C01", "EXP25-C06", "EXP25-M01")),
    (("--case-id", "M05", "--version", "2022.1"), ("EXP22-M05",)),
    (("--case-id", "EXP25-C01"), ("EXP25-C01",)),
))
def test_expansion_filters_are_exact_including_boundary_only(tmp_path, monkeypatch, surface, selection, expected):
    options = _options(tmp_path, monkeypatch, surface, *selection)
    units = (campaign.load_heavy_v3_campaign_units if surface == "campaign" else matrix.load_heavy_v3_units)(options)
    assert tuple(unit.unit_id for unit in units) == expected


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
@pytest.mark.parametrize("extra", (
    ("--version", "2024.1"), ("--case-id", "C99"),
    ("--case-id", "C01", "--case-id", "EXP25-C01"),
    ("--case-id", "EXP22-C01", "--version", "2025.1"),
    ("--model", "gpt-6.1-sol", "--reasoning-effort", "high"),
    ("--service-tier", "priority"), ("--timeout", "599"),
    ("--offline-only",), ("--pair-id", "C01"),
))
def test_expansion_rejects_unreviewed_or_ambiguous_selection(tmp_path, monkeypatch, surface, extra):
    with pytest.raises(SystemExit):
        _options(tmp_path, monkeypatch, surface, *extra)


@pytest.mark.parametrize("model,effort", (("gpt-6-luna", "high"), ("gpt-6.1-sol", "medium"), ("gpt-6-luna", "medium")))
def test_expansion_accepts_only_reviewed_pilot_options(tmp_path, monkeypatch, model, effort):
    options = _options(tmp_path, monkeypatch, "campaign", "--model", model, "--reasoning-effort", effort)
    assert options.model == model and options.reasoning_effort == effort
    assert options.max_pre_action_retries == 0


def test_expansion_requires_new_matrix_root_and_no_same_root_retry(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _options(tmp_path, monkeypatch, "matrix", "--overwrite")
    with pytest.raises(SystemExit):
        _options(tmp_path, monkeypatch, "campaign", "--max-pre-action-retries", "1")


def test_matrix_dispatches_expansion_runtime_with_frozen_digest(tmp_path, monkeypatch):
    from tests.semantic.support import codex_expansion_runtime as runtime
    options = _options(tmp_path, monkeypatch, "matrix", "--case-id", "C06", "--version", "2025.1")
    unit, = matrix.load_heavy_v3_units(options)
    calls = []
    monkeypatch.setattr(runtime, "run_expansion_unit", lambda unit, **kwargs: calls.append((unit, kwargs)) or "result")
    with pytest.raises(matrix.HeavyV3RunnerUnavailableError, match="immutable campaign"):
        matrix.run_heavy_v3_unit(unit, scenario_root=tmp_path / "scenario", options=options)
    assert calls == []
    options = replace(options, campaign_inputs_sha256="a" * 64)
    assert matrix.run_heavy_v3_unit(unit, scenario_root=tmp_path / "scenario", options=options) == "result"
    assert calls[0][1]["options"].campaign_inputs_sha256 == "a" * 64
    assert calls[0][1]["options"].timeout_seconds == 600
    assert calls[0][1]["options"].live_environment["WWISE_TEST_CONFIG"] == str(options.live_config)


def test_full_matrix_accounts_boundary_separately_from_thirteen_agent_passes(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_runtime import ExpansionOutcome
    options = _options(tmp_path, monkeypatch)
    units = matrix.load_heavy_v3_units(options)
    monkeypatch.setattr(matrix, "prepare_iteration_root", lambda root, **kwargs: root.mkdir())
    called = []
    def run(unit, *, scenario_root, options):
        called.append(unit.unit_id)
        boundary = unit.evidence_kind == "capability_boundary"
        return ExpansionOutcome(unit.unit_id, unit.version, "BOUNDARY_PROVEN" if boundary else "PASS", "",
            str(scenario_root), None if boundary else str(scenario_root / "task"),
            None if boundary else unit.unit_id + "-thread",
            {"capability_boundary": {"agent_started": False, "business_pass": False}} if boundary else {}, None, "a" * 64)
    assert matrix.run_heavy_v3_matrix(options, unit_runner=run, dependency_preflight=lambda: {"ok": True}) == 0
    summary = json.loads((options.iteration_root / "summary.json").read_text())
    assert called[0] == "EXP22-M05"
    assert summary["status_counts"]["PASS"] == 13
    assert summary["status_counts"]["BOUNDARY_PROVEN"] == 1
    assert "EXP22-M05" not in summary["passed_unit_ids"]
    assert summary["expansion_accounting"]["capability_boundaries"] == {
        "selected": ["EXP22-M05"], "proven": ["EXP22-M05"], "agent_pass_credit": False}
    campaign._validate_heavy_v3_summary(summary, expected_ids=tuple(unit.unit_id for unit in units),
        returncode=0, expected_profile=PROFILE,
        expected_rows=[campaign.heavy_v3_unit_row(unit, sequence=index) for index, unit in enumerate(units, 1)])


def test_boundary_cannot_be_promoted_to_agent_pass(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_runtime import ExpansionOutcome
    options = _options(tmp_path, monkeypatch, "matrix", "--case-id", "M05", "--version", "2022.1")
    unit, = matrix.load_heavy_v3_units(options)
    outcome = ExpansionOutcome(unit.unit_id, unit.version, "PASS", "", str(tmp_path), None, None, {}, None, "a" * 64)
    with pytest.raises(matrix.HeavyV3MatrixError, match="cannot grant Agent PASS"):
        matrix._heavy_v3_case_record(matrix._heavy_v3_unit_row(unit, sequence=1), scenario_root=tmp_path, outcome=outcome)


def test_campaign_child_preserves_exact_selection_and_input_digest(tmp_path, monkeypatch):
    options = _options(tmp_path, monkeypatch, "campaign", "--case-id", "C01", "--version", "2025.1")
    units = campaign.load_heavy_v3_campaign_units(options)
    options = replace(options, campaign_inputs_sha256="a" * 64)
    argv = campaign.build_heavy_v3_child_argv(options, units=units, matrix_root=tmp_path / "child")
    child = matrix.parse_args(argv[2:])
    assert child.case_ids == ("EXP25-C01",) and child.versions == ()
    assert child.campaign_inputs_sha256 == "a" * 64
    assert child.timeout_seconds == 600 and child.profile == PROFILE
    assert campaign.heavy_v3_immutable_options(options) == campaign.heavy_v3_immutable_options(
        replace(options, campaign_inputs_sha256="b" * 64))  # derived digest has no recursive self-hash


def _empty_sealed_campaign(tmp_path, monkeypatch):
    options = _options(tmp_path, monkeypatch, "campaign", "--case-id", "C06", "--version", "2025.1")
    options.campaign_root.mkdir()
    effective = {"codex": {"path": str(options.codex_binary), "version": "codex-cli 1.0",
                           "windows_powershell_core_host": None}}
    config = campaign.create_immutable_campaign_config(options.campaign_root, {
        "effective": effective,
        "effective_sha256": hashlib.sha256(campaign.canonical_json_bytes(effective)).hexdigest(),
    })
    campaign.write_campaign_marker(options.campaign_root, campaign_id=config["campaign_id"])
    return replace(options, resume=True, verify_only=True), effective


def test_verify_only_is_read_only_and_never_starts_processes(tmp_path, monkeypatch):
    options, effective = _empty_sealed_campaign(tmp_path, monkeypatch)
    units = campaign.load_heavy_v3_campaign_units(options)
    def fingerprint(received, **kwargs):
        assert kwargs["sealed_codex_version"] == "codex-cli 1.0"
        assert received.campaign_inputs_sha256 == hashlib.sha256(campaign.canonical_json_bytes(effective)).hexdigest()
        return effective
    monkeypatch.setattr(campaign, "build_heavy_v3_effective_config", fingerprint)
    monkeypatch.setattr(campaign.subprocess, "run", lambda *args, **kwargs: pytest.fail("verify-only launched a process"))
    monkeypatch.setattr(campaign, "run_child", lambda *args, **kwargs: pytest.fail("verify-only launched a matrix"))
    before = {path.relative_to(options.campaign_root): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in options.campaign_root.rglob("*") if path.is_file()}
    assert campaign.verify_expansion_campaign(options, units=units,
        required_units={unit.unit_id: (campaign._heavy_unit_phase(unit),) for unit in units}) == campaign.EXIT_PENDING
    after = {path.relative_to(options.campaign_root): (path.read_bytes(), path.stat().st_mtime_ns)
             for path in options.campaign_root.rglob("*") if path.is_file()}
    assert after == before


def test_verify_only_rejects_changed_frozen_inputs_without_running(tmp_path, monkeypatch):
    options, effective = _empty_sealed_campaign(tmp_path, monkeypatch)
    units = campaign.load_heavy_v3_campaign_units(options)
    monkeypatch.setattr(campaign, "build_heavy_v3_effective_config", lambda *args, **kwargs: {**effective, "drift": True})
    monkeypatch.setattr(campaign, "run_child", lambda *args, **kwargs: pytest.fail("must not execute"))
    with pytest.raises(campaign.CampaignEvidenceError, match="immutable inputs"):
        campaign.verify_expansion_campaign(options, units=units,
            required_units={unit.unit_id: (campaign._heavy_unit_phase(unit),) for unit in units})


def test_verify_only_parser_uses_sealed_executable_without_discovery(tmp_path, monkeypatch):
    options, _ = _empty_sealed_campaign(tmp_path, monkeypatch)
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda *args: pytest.fail("must not probe Codex"))
    monkeypatch.setattr(campaign, "discover_windows_powershell_core", lambda **kwargs: pytest.fail("must not probe shell"))
    parsed = campaign.parse_args(["--campaign-root", str(options.campaign_root), "--resume", "--verify-only",
        "--profile", PROFILE, "--codex-binary", str(options.codex_binary),
        "--auth-json", str(options.auth_json), "--live-config", str(options.live_config)])
    assert parsed.codex_binary == options.codex_binary


def test_expansion_outcome_requires_independent_archive_verifier(tmp_path, monkeypatch):
    from tests.semantic.support import codex_expansion_archive as archive
    options = replace(_options(tmp_path, monkeypatch, "campaign", "--case-id", "C06", "--version", "2025.1"),
                      campaign_inputs_sha256="a" * 64)
    unit, = campaign.load_heavy_v3_campaign_units(options)
    seen = []
    def fail(root, **kwargs):
        seen.append((root, kwargs))
        raise archive.ExpansionArchiveError("altered sealed budget")
    monkeypatch.setattr(archive, "verify_expansion_task_archive", fail)
    outcome = {"status": "PASS", "task_root": str(tmp_path / "task"), "checks": {"task": {"passed": True}}}
    with pytest.raises(campaign.CampaignEvidenceError, match="altered sealed budget"):
        campaign._validate_expansion_outcome(outcome, expected_unit=unit, scenario_root=tmp_path, options=options)
    assert seen == [(tmp_path / "task", {"expected_unit_id": "EXP25-C06", "expected_version": "2025.1",
                                         "expected_inputs_sha256": "a" * 64})]


@pytest.mark.parametrize("task_status", ("FAIL", "BLOCKED", "INDETERMINATE"))
def test_expansion_campaign_preserves_classified_negative_archive(tmp_path, monkeypatch, task_status):
    from tests.semantic.support import codex_expansion_archive as archive
    options = replace(_options(tmp_path, monkeypatch, "campaign", "--case-id", "C06", "--version", "2025.1"),
                      campaign_inputs_sha256="a" * 64)
    unit, = campaign.load_heavy_v3_campaign_units(options)
    lifecycle = {"scenario_id": unit.unit_id, "version": unit.version,
                 "source_hash_before": {"sha256": "source"}, "source_hash_after": {"sha256": "source"},
                 "source_mtime_before_ns": 1, "source_mtime_after_ns": 1}
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "lifecycle.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    monkeypatch.setattr(archive, "verify_expansion_task_archive", lambda *args, **kwargs: {
        "archive_valid": True, "original_status": task_status, "business_pass": False})
    outcome = {"status": task_status, "task_root": str(tmp_path / "task"), "lifecycle": lifecycle,
               "checks": {"task": {"passed": False, "status": task_status}}}
    campaign._validate_expansion_outcome(outcome, expected_unit=unit, scenario_root=tmp_path, options=options)
    outcome["checks"]["task"]["status"] = "PASS"
    with pytest.raises(campaign.CampaignEvidenceError):
        campaign._validate_expansion_outcome(outcome, expected_unit=unit, scenario_root=tmp_path, options=options)


def test_boundary_replays_through_real_campaign_seal_and_archive_verifier(tmp_path, monkeypatch):
    """Only the external Wwise observation is fake; sealing and replay are real."""
    from tests.semantic.support.codex_expansion_runtime import ExpansionOutcome
    options, effective = _empty_sealed_campaign(tmp_path, monkeypatch)
    digest = hashlib.sha256(campaign.canonical_json_bytes(effective)).hexdigest()
    options = replace(options, case_ids=("M05",), versions=("2022.1",), campaign_inputs_sha256=digest)
    units = campaign.load_heavy_v3_campaign_units(options)
    _, attempt = campaign.create_attempt(options.campaign_root)
    group = attempt / "runs" / campaign.HEAVY_V3_GROUP_ID
    group.mkdir(parents=True)
    matrix_root = group / "matrix"
    argv = campaign.build_heavy_v3_child_argv(options, units=units, matrix_root=matrix_root)
    child = matrix.parse_args(argv[2:])
    monkeypatch.setattr(matrix, "prepare_iteration_root", lambda path, **kwargs: path.mkdir())
    def run(unit, *, scenario_root, options):
        evidence = {"identity_before": {"id": "owned-stinger"}, "identity_after": {"id": "owned-stinger"},
            "agent_executed": False, "business_effect_verified": False,
            "public_observation": {"ok": True, "status": "needs_clarification", "agent_result": {
                "unresolved": [{"meaning": "Trigger", "candidate_names": []},
                               {"meaning": "Segment", "candidate_names": []}]}}}
        lifecycle = {"scenario_id": unit.unit_id, "version": unit.version,
            "requested_status": "BLOCKED", "final_status": "BLOCKED",
            "source_hash_before": {"sha256": "source"}, "source_hash_after": {"sha256": "source"},
            "source_mtime_before_ns": 1, "source_mtime_after_ns": 1}
        outcome = ExpansionOutcome(unit.unit_id, unit.version, "BOUNDARY_PROVEN", "reviewed unavailable reference",
            str(scenario_root), None, None, {"capability_boundary": {"case_id": "M05", "version": "2022.1",
                "boundary_code": "CAPABILITY_UNAVAILABLE", "evidence": evidence,
                "agent_started": False, "business_pass": False}}, lifecycle, digest)
        matrix.write_json(scenario_root / "outcome.json", outcome.as_dict())
        matrix.write_json(scenario_root / "evidence" / "lifecycle.json", lifecycle)
        return outcome
    preflight = {"contract": campaign.HEAVY_V3_LIVE_PREFLIGHT_CONTRACT, "ok": True,
        "dependency": "waapi-client", "module": "waapi", "required_symbols": ["WaapiClient", "WaapiRequestFailed"],
        "current_interpreter": str(Path(campaign.sys.executable).resolve()), "automatic_install_attempted": False}
    assert matrix.run_heavy_v3_matrix(child, unit_runner=run, dependency_preflight=lambda: preflight) == 0
    campaign.atomic_write_json_with_digest(group / "child-request.json",
        campaign.heavy_v3_child_request(options, units=units, argv=argv))
    campaign.atomic_write_json_with_digest(group / "child-result.json", {
        "contract": campaign.CHILD_EXECUTION_CONTRACT, "group_id": campaign.HEAVY_V3_GROUP_ID,
        "returncode": 0, "completed_at": campaign.utc_now()})
    validation = campaign.validate_heavy_v3_child_run(matrix_root, expected_units=units, options=options, returncode=0)
    assert list(validation.observations) == [{"unit_id": "EXP22-M05", "status": "PASS",
        "phases": [{"phase": "capability-boundary", "status": "PASS"}]}]
    campaign.seal_attempt(attempt, validation.observations)
    monkeypatch.setattr(campaign, "build_heavy_v3_effective_config", lambda *args, **kwargs: effective)
    monkeypatch.setattr(campaign.subprocess, "run", lambda *args, **kwargs: pytest.fail("archive replay launched a process"))
    assert campaign.verify_expansion_campaign(options, units=units,
        required_units={"EXP22-M05": ("capability-boundary",)}) == 0
    outcome_path, = matrix_root.glob("scenarios/*/outcome.json")
    outcome_path.write_text("{}")
    with pytest.raises(campaign.CampaignEvidenceError):
        campaign.verify_expansion_campaign(options, units=units,
            required_units={"EXP22-M05": ("capability-boundary",)})
